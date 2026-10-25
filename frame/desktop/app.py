#!/usr/bin/env python3
"""FramePhone's desktop test window. No shell commands or runtime container."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from front_cameras import DEFAULT_CAMERAS, MAPPING_VERSION, default_selection, factory_cameras, mono_streams
from camera_previews import CameraPreviews


def host_environment():
    """Host polkit/file manager must never load the bundled Python or libc."""
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("LD_", "PYTHON", "TCL_", "TK_", "FRAMEPHONE_"))}


class Runtime:
    def __init__(self):
        self.root = Path(os.environ["FRAMEPHONE_RUNTIME_ROOT"])
        self.loader = os.environ["FRAMEPHONE_LOADER"]
        self.libraries = os.environ["FRAMEPHONE_LIBRARY_PATH"]
        self.ring = Path(f"/run/user/{os.getuid()}/framephone-camera/cam-ring")

    def command(self, tool, *args):
        return [self.loader, "--library-path", self.libraries,
                str(self.root / "opt/framephone/bin" / f"framephone-{tool}"), *map(str, args)]

    def calibration_id(self):
        digest = hashlib.sha256()
        for name in ("xrservice.json", "device_config.json"):
            digest.update((Path("/persist") / name).read_bytes())
        return "factory-sha256-" + digest.hexdigest()

    def camera_command(self):
        pkexec = shutil.which("pkexec", path=host_environment().get("PATH"))
        if not pkexec:
            raise ValueError("The desktop's pkexec authorization tool is missing.")
        return [pkexec, "--disable-internal-agent",
                str(self.root / "opt/framephone/bin/framephone-camd"),
                "--status", "0"]



class Window:
    def __init__(self, root, runtime):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        self.root, self.runtime = root, runtime
        self.preview_reader = CameraPreviews(runtime)
        self.preview_updated = [0, 0]
        self.preview_selected = ["", ""]
        self.events = queue.SimpleQueue()
        self.processes, self.jobs, self.stopping = {}, set(), set()
        self.closing = False
        self.factories, self.available_streams, self.stream_info = {}, [], {}
        self.factory_boxes, self.stream_boxes = [], []
        self.self_test_result = None
        self.config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "framephone/settings.json"
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "framephone"
        self.sessions = state / "sessions"
        state.mkdir(parents=True, exist_ok=True)
        self.lock = (state / "desktop.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("FramePhone is already open. Use the existing window.") from None
        self.logfile = (state / "desktop.log").open("a", buffering=1)
        try:
            saved = json.loads(self.config.read_text())
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        mapping = saved if saved.get("mapping_version") == MAPPING_VERSION else {}
        for key in ("left", "right", "left_stream", "right_stream"):
            setattr(self, key, tk.StringVar(value=mapping.get(key, "")))
        self.show_views = tk.BooleanVar(value=bool(saved.get("show_camera_views", True)))
        self.status = tk.StringVar(value="Pair the phone, show its fullscreen marker, then open Marker tracking.")
        root.title("FramePhone")
        root.geometry("1000x900")
        root.minsize(720, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Label(root, textvariable=self.status, wraplength=950, padding=8).pack(side="bottom", fill="x")
        self.tabs = tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True)
        phone_tab, marker_tab, camera_tab = (ttk.Frame(tabs) for _ in range(3))
        tabs.add(phone_tab, text="Phone telemetry")
        tabs.add(marker_tab, text="Marker tracking")
        tabs.add(camera_tab, text="Diagnostics")
        from phone_panel import PhonePanel
        self.phone_panel = PhonePanel(phone_tab, self.config.parent)
        from fiducial_panel import FiducialPanel
        self.tracking_panel = FiducialPanel(marker_tab, self)
        panel = ttk.Frame(camera_tab, padding=16)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        ttk.Label(panel, text="Diagnostics", font=("sans", 16, "bold")).grid(row=0, column=0, sticky="w")
        actions = ttk.Frame(panel)
        actions.grid(row=1, column=0, sticky="ew", pady=10)
        self.test_button = ttk.Button(actions, text="Geometry self-test", command=self.self_test)
        self.test_button.pack(side="left")
        ttk.Button(actions, text="Open results", command=lambda: self.open_folder(self.sessions)).pack(side="left", padx=8)
        self.output = ScrolledText(panel, height=10, state="disabled", font=("monospace", 9))
        self.output.grid(row=2, column=0, sticky="nsew", pady=8)
        root.after(100, self.drain)
        root.after(250, self.update_previews)

    def log(self, message):
        self.logfile.write(message + "\n")
        self.output.configure(state="normal")
        self.output.insert("end", message + "\n")
        if int(self.output.index("end-1c").split(".")[0]) > 2000:
            self.output.delete("1.0", "1000.0")
        self.output.see("end")
        self.output.configure(state="disabled")

    def save(self):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        temp = self.config.with_suffix(".tmp")
        settings = {key: getattr(self, key).get() for key in
                    ("left", "right", "left_stream", "right_stream")}
        settings["show_camera_views"] = self.show_views.get()
        settings["mapping_version"] = MAPPING_VERSION
        temp.write_text(json.dumps(settings, indent=2) + "\n")
        temp.replace(self.config)

    def toggle_views(self):
        self.tracking_panel.set_camera_views(self.show_views.get())
        self.save()

    def spawn(self, name, command, env=None):
        if name in self.processes:
            return False
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors="replace", bufsize=1, env=env)
        except OSError as error:
            self.status.set(str(error))
            return False
        self.processes[name] = process

        def read():
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    self.events.put(("line", name, line))
            finally:
                process.stdout.close()
                self.events.put(("exit", name, process.wait()))
        threading.Thread(target=read, daemon=True).start()
        return True

    def self_test(self):
        if "self-test" not in self.processes:
            self.self_test_result = None
            self.status.set("Running synthetic marker-pose self-test…")
            self.test_button.configure(state="disabled")
            if not self.spawn("self-test", self.runtime.command("fiducial", "--self-test")):
                self.test_button.configure(state="normal")
                self.self_test_result = False

    def enable_cameras(self):
        try:
            command = self.runtime.camera_command()
            self.runtime.calibration_id()  # Fail clearly on a PC before prompting for root.
            self.status.set("Approve the desktop authorization prompt, then wait for camera frames.")
            self.spawn("camera", command, host_environment())
            if "camera" in self.processes:
                self.camera_button.configure(state="disabled")
                self.root.after(1500, self.refresh)
        except (OSError, ValueError) as error:
            self.status.set(f"Cannot enable cameras: {error}")
            self.log(str(error))

    def refresh(self):
        if self.tracking_panel.busy:
            self.status.set("Stop tracking before refreshing the camera mapping.")
            return
        if "scan" in self.jobs:
            return
        self.jobs.add("scan")
        def scan():
            try:
                revision = self.runtime.calibration_id()
                factory = subprocess.run(self.runtime.command("camera", "--list-cameras", "--calibration-id", revision, "--factory-root", getattr(self.runtime, "factory_root", Path("/"))), capture_output=True, text=True, timeout=10, check=True)
                streams = subprocess.run(self.runtime.command("camera", "--list-ring", self.runtime.ring), capture_output=True, text=True, timeout=10, check=True)
                self.events.put(("scan", factory.stdout, streams.stdout))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                detail = getattr(error, "stderr", "") or str(error)
                self.events.put(("scan-error", "", detail))
        threading.Thread(target=scan, daemon=True).start()

    def terminate(self, name):
        process = self.processes.get(name)
        if process and process.poll() is None:
            self.stopping.add(name)
            try:
                process.terminate()
                self.root.after(2000, lambda: self.kill(process))
            except PermissionError:
                pass  # Root setup is brief; broker's parent-death signal covers close.

    @staticmethod
    def kill(process):
        if process.poll() is None:
            try:
                process.kill()
            except (ProcessLookupError, PermissionError):
                pass

    def drain(self):
        for _ in range(200):
            try:
                kind, name, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self.log(f"[{name}] {value}")
                if name == "overlay":
                    self.tracking_panel.vr_status.set(value)
                if name == "camera" and "without privileges" in value:
                    self.refresh()
            elif kind == "exit":
                self.processes.pop(name, None)
                self.stopping.discard(name)
                self.log(f"[{name}] exited with status {value}")
                if name == "camera":
                    self.camera_button.configure(state="normal")
                    self.status.set("Camera broker stopped. Enable cameras to retry.")
                    if self.tracking_panel.busy:
                        self.tracking_panel.stop()
                elif name == "overlay":
                    self.tracking_panel.vr_status.set("VR display stopped. See Diagnostics log." if value else "VR display closed.")
                elif name == "self-test":
                    self.self_test_result = value == 0
                    self.test_button.configure(state="normal")
                    self.status.set("Geometry self-test passed (synthetic; hardware accuracy is unverified)." if value == 0 else "Geometry self-test failed; see log.")
            elif kind == "scan":
                self.jobs.discard("scan")
                self.factories = factory_cameras(name)
                self.stream_info = mono_streams(value)
                self.available_streams = list(self.stream_info)
                for box in self.stream_boxes:
                    box.configure(values=self.available_streams)
                for box in self.factory_boxes:
                    box.configure(values=list(self.factories))
                for calibration, stream, (default_calibration, default_stream) in zip(
                        (self.left, self.right), (self.left_stream, self.right_stream), DEFAULT_CAMERAS):
                    calibration.set(default_selection(calibration.get(), self.factories, default_calibration))
                    stream.set(default_selection(stream.get(), self.available_streams, default_stream))
                self.save()
                self.log("Factory cameras:\n" + name + "Live streams:\n" + value)
                self.status.set("Front defaults use video3/slam_left and video0/slam_right when available. Verify lenses and calibration mapping.")
            else:
                self.jobs.discard("scan")
                self.log("Camera discovery: " + str(value))
                self.status.set("Cameras are not ready. Retry Enable/Refresh cameras; see Diagnostics log.")
        if not self.closing:
            self.root.after(100, self.drain)

    def update_previews(self):
        import tkinter as tk
        if self.closing:
            return
        visible = self.show_views.get() and self.tracking_panel.parent.winfo_ismapped()
        for index, stream in enumerate((self.left_stream.get(), self.right_stream.get())):
            self.preview_reader.update(index, stream, visible)
            if not visible:
                self.preview_updated[index] = 0
                continue
            changed = self.preview_selected[index] != stream
            if changed:
                self.preview_selected[index] = stream
                self.preview_updated[index] = 0
            item = self.preview_reader.take(index)
            if item is None and not changed and time.monotonic()-self.preview_updated[index] < 1.5:
                continue
            result, error = item if item else (None, "Waiting for camera frames…" if stream else "Select a camera stream.")
            if item is not None:
                self.preview_updated[index] = time.monotonic()
            try:
                self.tracking_panel.camera_preview(index, stream, result, error)
            except (ValueError, tk.TclError) as exc:
                self.tracking_panel.camera_preview(index, stream, None, str(exc))
        if not self.closing:
            self.root.after(100, self.update_previews)

    def open_folder(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        opener = shutil.which("xdg-open", path=host_environment().get("PATH"))
        if opener:
            subprocess.Popen([opener, str(folder)], env=host_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.status.set("Results: " + str(folder))

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.preview_reader.close()
        self.tracking_panel.close()
        self.phone_panel.close()
        for name in list(self.processes):
            self.terminate(name)
        deadline = time.monotonic() + 3
        def finish():
            active = [p for name, p in self.processes.items() if name != "camera" and p.poll() is None]
            with self.tracking_panel.process_lock:
                process = self.tracking_panel.process
                if process and process.poll() is None:
                    active.append(process)
            if active and time.monotonic() < deadline:
                self.root.after(100, finish)
                return
            for process in active:
                self.kill(process)
            self.root.destroy()
        self.root.after(100, finish)


def main():
    parser = argparse.ArgumentParser(description="FramePhone desktop tracking test")
    parser.add_argument("--gui-smoke", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    try:
        window = Window(root, Runtime())
    except (OSError, ValueError) as error:
        root.withdraw()
        messagebox.showerror("FramePhone", str(error))
        return 1
    exit_status = 0
    if args.gui_smoke:
        photo = tk.PhotoImage(data=b"P5\n2 2\n255\n\x00\x46\x96\xff", format="PPM")
        assert photo.width() == 2 and photo.height() == 2
        # Exercise the actual button, worker pipe and packaged native geometry solver.
        deadline = time.monotonic() + 15
        def check_smoke():
            nonlocal exit_status
            if window.self_test_result is None and time.monotonic() < deadline:
                root.after(100, check_smoke)
                return
            exit_status = 0 if window.self_test_result is True else 1
            window.close()
        root.after(100, window.self_test)
        root.after(200, check_smoke)
    root.mainloop()
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())

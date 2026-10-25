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

from front_cameras import FRONT_CAMERAS, factory_cameras, mono_streams, validate_front_cameras
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
    def __init__(self, root, runtime, autostart=True):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        self.root, self.runtime = root, runtime
        self.preview_reader = CameraPreviews(runtime)
        self.preview_updated = [0, 0]
        self.events = queue.SimpleQueue()
        self.processes, self.jobs, self.stopping = {}, set(), set()
        self.closing = False
        self.factories = {}
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
        self.show_views = tk.BooleanVar(value=bool(saved.get("show_camera_views", True)))
        self.status = tk.StringVar(value="Starting cameras and phone discovery…")
        root.title("FramePhone")
        root.geometry("1000x900")
        root.minsize(720, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Label(root, textvariable=self.status, wraplength=680, padding=8).pack(side="bottom", fill="x")
        dashboard = ttk.Frame(root, padding=8)
        dashboard.pack(fill="both", expand=True)
        dashboard.columnconfigure(0, weight=1)
        dashboard.rowconfigure(1, weight=1)
        phone_area = ttk.Frame(dashboard)
        phone_area.grid(row=0, column=0, sticky="ew")
        tracking_area = ttk.Frame(dashboard)
        tracking_area.grid(row=1, column=0, sticky="nsew")
        from phone_panel import PhonePanel
        self.phone_panel = PhonePanel(phone_area, self.config.parent)
        from fiducial_panel import FiducialPanel
        self.tracking_panel = FiducialPanel(tracking_area, self)
        self.log_panel = ttk.LabelFrame(dashboard, text="Activity log", padding=6)
        self.log_panel.grid(row=2, column=0, sticky="ew")
        self.log_panel.columnconfigure(0, weight=1)
        actions = ttk.Frame(self.log_panel)
        actions.grid(row=0, column=0, sticky="ew")
        self.test_button = ttk.Button(actions, text="Geometry self-test", command=self.self_test)
        self.test_button.pack(side="left")
        self.output = ScrolledText(self.log_panel, height=5, state="disabled", font=("monospace", 9))
        self.output.grid(row=1, column=0, sticky="ew", pady=4)
        self.log_panel.grid_remove()
        if autostart:
            root.after(200, self.startup)
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
        settings = {"show_camera_views": self.show_views.get()}
        temp.write_text(json.dumps(settings, indent=2) + "\n")
        temp.replace(self.config)

    @property
    def camera_selection(self):
        return tuple(item[0] for item in FRONT_CAMERAS) + tuple(item[1] for item in FRONT_CAMERAS)

    def startup(self):
        if not self.closing:
            self.enable_cameras()
            self.phone_panel.startup()

    def toggle_log(self):
        if self.log_panel.winfo_manager():
            self.log_panel.grid_remove()
        else:
            self.log_panel.grid()

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
        if "camera" in self.processes:
            self.refresh()
            return
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
                    self.status.set("Camera broker stopped. Use Retry cameras.")
                    if self.tracking_panel.busy:
                        self.tracking_panel.stop()
                elif name == "overlay":
                    self.tracking_panel.vr_status.set("VR display stopped. See the activity log." if value else "VR display closed.")
                elif name == "self-test":
                    self.self_test_result = value == 0
                    self.test_button.configure(state="normal")
                    self.status.set("Geometry self-test passed (synthetic; hardware accuracy is unverified)." if value == 0 else "Geometry self-test failed; see log.")
            elif kind == "scan":
                self.jobs.discard("scan")
                self.factories = factory_cameras(name)
                streams = mono_streams(value)
                self.camera_button.configure(state="normal")
                try:
                    validate_front_cameras(self.factories, streams)
                    self.status.set("Front cameras ready · left video3 · right video0")
                except ValueError as error:
                    self.status.set(str(error))
                self.log("Factory cameras:\n" + name + "Live streams:\n" + value)
            else:
                self.jobs.discard("scan")
                self.log("Camera discovery: " + str(value))
                self.camera_button.configure(state="normal")
                self.status.set("Cameras are not ready. Retry cameras; see the activity log.")
        if not self.closing:
            self.root.after(100, self.drain)

    def update_previews(self):
        import tkinter as tk
        if self.closing:
            return
        visible = (self.show_views.get() and self.tracking_panel.parent.winfo_ismapped()
                   and not self.tracking_panel.busy)
        for index, (_, stream) in enumerate(FRONT_CAMERAS):
            self.preview_reader.update(index, stream, visible)
            if not visible:
                self.preview_updated[index] = 0
                continue
            item = self.preview_reader.take(index)
            if item is None and time.monotonic()-self.preview_updated[index] < 1.5:
                continue
            result, error = item if item else (None, "Waiting for camera frames…" if stream else "Select a camera stream.")
            if item is not None:
                self.preview_updated[index] = time.monotonic()
            try:
                self.tracking_panel.camera_preview(index, result, error)
            except (ValueError, tk.TclError) as exc:
                self.tracking_panel.camera_preview(index, None, str(exc))
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
    parser = argparse.ArgumentParser(description="FramePhone tracking dashboard")
    parser.add_argument("--gui-smoke", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    try:
        window = Window(root, Runtime(), autostart=not args.gui_smoke)
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

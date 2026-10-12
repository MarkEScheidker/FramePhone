#!/usr/bin/env python3
"""FramePhone's desktop test window. No shell commands or runtime container."""
import argparse
from datetime import datetime, timezone
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
import uuid


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
                str(self.root / "opt/framephone/bin/framephone-camd"), "--status", "2"]

    def tracking_command(self, layout, left, right, left_stream, right_stream, session, record):
        if not Path(layout).is_file():
            raise ValueError("Choose the measured phone layout exported from the Android app.")
        if not all((left, right, left_stream, right_stream)):
            raise ValueError("Select both calibrated cameras and both corresponding live streams.")
        if left == right or left_stream == right_stream:
            raise ValueError("Left and right must use different cameras and streams.")
        revision = self.calibration_id()
        session.mkdir(parents=True, exist_ok=False)
        # Keep the exact layout used by this session, even if the phone is recalibrated later.
        shutil.copyfile(layout, session / "layout.json")
        args = ["--ring", self.ring, "--left", left, "--right", right,
                "--left-ring", left_stream, "--right-ring", right_stream,
                "--calibration-id", revision, "--phone-layout", session / "layout.json",
                # Pinned broker's mono streams share V4L2 capture timestamps.
                # The domain label is an assumption to validate on hardware;
                # no conversion to OpenXR/world time is made here.
                "--capture-clock", "steam-frame-mono-v4l2", "--frames", "1000000",
                "--idle-timeout-ms", "15000", "--pose-jsonl", session / "poses.jsonl",
                "--csv", session / "tracking.csv"]
        if record:
            args += ["--record-dir", session / "paired-images"]
        (session / "session.json").write_text(json.dumps({
            "calibration_id": revision, "left": left, "right": right,
            "left_stream": left_stream, "right_stream": right_stream,
            "capture_clock_assumption": "steam-frame-mono-v4l2",
        }, indent=2) + "\n")
        return self.command("stereo", *args)


class Window:
    def __init__(self, root, runtime):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
        self.root, self.runtime = root, runtime
        self.events = queue.SimpleQueue()
        self.processes = {}
        self.jobs = set()
        self.closing = False
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
        self.layout = tk.StringVar(value=saved.get("layout", ""))
        self.left = tk.StringVar(value=saved.get("left", "slam_left"))
        self.right = tk.StringVar(value=saved.get("right", "slam_right"))
        self.left_stream = tk.StringVar(value=saved.get("left_stream", ""))
        self.right_stream = tk.StringVar(value=saved.get("right_stream", ""))
        self.record = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Choose a phone layout, then enable cameras.")
        self.pose = tk.StringVar(value="No phone pose yet")
        root.title("FramePhone — tracking test")
        root.geometry("920x780")
        root.minsize(720, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(root, padding=16)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(9, weight=1)
        ttk.Label(panel, text="FramePhone", font=("sans", 20, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(panel, text="Experimental front-camera stereo tracking • head-relative position and rotation").grid(row=1, column=0, sticky="w", pady=(0, 12))
        file_row = ttk.Frame(panel)
        file_row.grid(row=2, column=0, sticky="ew")
        ttk.Button(file_row, text="Choose phone layout…", command=self.choose_layout).pack(side="left")
        ttk.Entry(file_row, textvariable=self.layout, state="readonly").pack(side="left", fill="x", expand=True, padx=8)
        actions = ttk.Frame(panel)
        actions.grid(row=3, column=0, sticky="ew", pady=12)
        self.camera_button = ttk.Button(actions, text="Enable cameras", command=self.enable_cameras)
        self.camera_button.pack(side="left")
        ttk.Button(actions, text="Refresh cameras", command=self.refresh).pack(side="left", padx=8)
        self.test_button = ttk.Button(actions, text="Self-test", command=self.self_test)
        self.test_button.pack(side="left")
        ttk.Button(actions, text="Open test results", command=lambda: self.open_folder(self.sessions)).pack(side="right")
        cameras = ttk.LabelFrame(panel, text="Match the two front cameras (cover each lens to identify its stream)", padding=8)
        cameras.grid(row=4, column=0, sticky="ew")
        cameras.columnconfigure(1, weight=1)
        cameras.columnconfigure(2, weight=1)
        ttk.Label(cameras, text="Factory calibration").grid(row=0, column=1)
        ttk.Label(cameras, text="Live stream").grid(row=0, column=2)
        self.factory_boxes, self.stream_boxes, self.previews = [], [], []
        for row, (label, factory, stream) in enumerate((("Front left", self.left, self.left_stream), ("Front right", self.right, self.right_stream)), 1):
            ttk.Label(cameras, text=label).grid(row=row, column=0, padx=4)
            box = ttk.Combobox(cameras, textvariable=factory, state="readonly")
            box.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
            self.factory_boxes.append(box)
            box = ttk.Combobox(cameras, textvariable=stream, state="readonly")
            box.grid(row=row, column=2, sticky="ew", padx=4, pady=4)
            self.stream_boxes.append(box)
        for column, title in ((1, "Front left preview"), (2, "Front right preview")):
            frame = ttk.Frame(cameras)
            frame.grid(row=3, column=column, pady=6)
            ttk.Label(frame, text=title).pack()
            preview = ttk.Label(frame, text="Waiting for camera frames", anchor="center")
            preview.pack()
            self.previews.append(preview)
        options = ttk.Frame(panel)
        options.grid(row=5, column=0, sticky="ew", pady=10)
        self.start_button = ttk.Button(options, text="Start tracking", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(options, text="Stop", command=self.stop_tracking).pack(side="left", padx=8)
        ttk.Checkbutton(options, text="Record paired images (uses disk space)", variable=self.record).pack(side="left")
        ttk.Label(panel, textvariable=self.status, wraplength=850).grid(row=6, column=0, sticky="w")
        ttk.Label(panel, textvariable=self.pose, font=("monospace", 12), wraplength=850).grid(row=7, column=0, sticky="w", pady=8)
        ttk.Label(panel, text="Camera access asks for desktop authorization. Closing this window stops its camera broker.").grid(row=8, column=0, sticky="w")
        self.output = ScrolledText(panel, height=10, state="disabled", font=("monospace", 9))
        self.output.grid(row=9, column=0, sticky="nsew", pady=(8, 0))
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
        temp.write_text(json.dumps({key: getattr(self, key).get() for key in
                                  ("layout", "left", "right", "left_stream", "right_stream")}, indent=2) + "\n")
        temp.replace(self.config)

    def choose_layout(self):
        from tkinter import filedialog
        name = filedialog.askopenfilename(title="Choose Android phone layout export", filetypes=[("JSON layout", "*.json"), ("All files", "*")])
        if name:
            self.layout.set(name)
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
                    self.events.put(("line", name, line.rstrip()))
            finally:
                process.stdout.close()
                self.events.put(("exit", name, process.wait()))
        threading.Thread(target=read, daemon=True).start()
        return True

    def self_test(self):
        if "self-test" not in self.processes:
            self.self_test_result = None
            self.status.set("Running synthetic detector self-test…")
            self.test_button.configure(state="disabled")
            if not self.spawn("self-test", self.runtime.command("diagnostic", "--headless", "--frames", "3", "--fps", "240")):
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
        if "scan" in self.jobs:
            return
        self.jobs.add("scan")
        def scan():
            try:
                revision = self.runtime.calibration_id()
                factory = subprocess.run(self.runtime.command("stereo", "--list-cameras", "--calibration-id", revision), capture_output=True, text=True, timeout=10, check=True)
                streams = subprocess.run(self.runtime.command("stereo", "--list-ring", self.runtime.ring), capture_output=True, text=True, timeout=10, check=True)
                self.events.put(("scan", factory.stdout, streams.stdout))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                detail = getattr(error, "stderr", "") or str(error)
                self.events.put(("scan-error", "", detail))
        threading.Thread(target=scan, daemon=True).start()

    def start(self):
        if "tracker" in self.processes:
            return
        try:
            factory = self.factory_boxes[0]["values"]
            streams = self.stream_boxes[0]["values"]
            if self.left.get() not in factory or self.right.get() not in factory or self.left_stream.get() not in streams or self.right_stream.get() not in streams:
                raise ValueError("Enable and refresh cameras, then match the front left and right streams.")
            session = self.sessions / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
            command = self.runtime.tracking_command(self.layout.get(), self.left.get(), self.right.get(), self.left_stream.get(), self.right_stream.get(), session, self.record.get())
            self.save()
            self.log("Test results: " + str(session))
            self.spawn("tracker", command)
            if "tracker" in self.processes:
                self.start_button.configure(state="disabled")
                self.status.set("Tracking. Hold the phone with tags visible to both front cameras.")
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def stop_tracking(self):
        self.terminate("tracker")
        self.pose.set("Tracking stopped")

    def terminate(self, name):
        process = self.processes.get(name)
        if process and process.poll() is None:
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
                if name == "tracker" and value.startswith("pair="):
                    self.pose.set(value)
                if name == "camera" and "without privileges" in value:
                    self.refresh()
            elif kind == "exit":
                self.processes.pop(name, None)
                self.log(f"[{name}] exited with status {value}")
                if name == "camera":
                    self.camera_button.configure(state="normal")
                    self.status.set("Camera broker stopped. Enable cameras to retry; details are below.")
                    self.stop_tracking()
                elif name == "tracker":
                    self.start_button.configure(state="normal")
                    self.status.set(f"Tracking stopped (status {value}). Results saved; see log below.")
                    self.pose.set("No live phone pose")
                else:
                    self.self_test_result = value == 0
                    self.test_button.configure(state="normal")
                    self.status.set("Self-test passed: detector processed three synthetic frames." if value == 0 else "Self-test failed; see log below.")
            elif kind == "scan":
                self.jobs.discard("scan")
                factories = [line.split()[0] for line in name.splitlines() if line.strip()]
                streams = [line.split()[0] for line in value.splitlines() if line.strip() and line.endswith("flags=0")]
                for box in self.factory_boxes:
                    box.configure(values=factories)
                for box in self.stream_boxes:
                    box.configure(values=streams)
                self.log("Factory cameras:\n" + name + "Live streams:\n" + value)
                self.status.set("Choose the corresponding front camera streams, check their previews, then start tracking.")
            else:
                self.jobs.discard("scan")
                self.log("Camera discovery: " + str(value))
                self.status.set("Cameras are not ready. Approve authorization or retry Enable/Refresh cameras.")
        if not self.closing:
            self.root.after(100, self.drain)

    def update_previews(self):
        import tkinter as tk
        from ring_preview import preview
        for widget, stream in zip(self.previews, (self.left_stream, self.right_stream)):
            try:
                result = preview(self.runtime.ring, stream.get()) if stream.get() else None
                if result:
                    width, height, pgm = result
                    # Tk's PPM decoder also accepts grayscale P5/PGM data.
                    image = tk.PhotoImage(data=pgm, format="PPM")
                    image = image.subsample(max(1, (width + 279) // 280, (height + 179) // 180))
                    widget.configure(image=image, text="")
                    widget.image = image
                else:
                    widget.configure(image="", text="Waiting for selected stream")
            except (OSError, ValueError, tk.TclError):
                widget.configure(image="", text="No live preview")
        if not self.closing:
            self.root.after(250, self.update_previews)

    def open_folder(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        opener = shutil.which("xdg-open", path=host_environment().get("PATH"))
        if opener:
            subprocess.Popen([opener, str(folder)], env=host_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.status.set("Results: " + str(folder))

    def close(self):
        self.closing = True
        for name in list(self.processes):
            self.terminate(name)
        # Let tracking flush before the self-extractor removes its runtime.
        deadline = time.monotonic() + 3
        def finish():
            active = [p for name, p in self.processes.items() if name != "camera" and p.poll() is None]
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
        # Exercise the actual button, worker pipe and packaged native detector.
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

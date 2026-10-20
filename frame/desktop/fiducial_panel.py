"""Automatic single-tag pose workflow; camera and TLS ownership remain separate."""
import hashlib
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

from phone_link import validate_fiducial


def create_session(directory, snapshot, factory_root, selections, ring, record):
    if not snapshot:
        raise ValueError("Connect your phone in Phone telemetry first.")
    target = validate_fiducial(snapshot.get("fiducial"))
    if target is None:
        raise ValueError("Update the Android app and reconnect. A valid automatic marker profile is required.")
    left, right, left_stream, right_stream = selections
    if not all(selections) or left == right or left_stream == right_stream:
        raise ValueError("Choose two distinct front streams and matching factory calibrations.")
    calibration = [(name, (factory_root / "persist" / name).read_bytes())
                   for name in ("xrservice.json", "device_config.json")]
    digest = hashlib.sha256(b"".join(data for _, data in calibration)).hexdigest()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    destination = directory / "factory/persist"
    destination.mkdir(parents=True)
    for name, data in calibration:
        (destination / name).write_bytes(data)
    config = {"schema": "framephone-fiducial-session-v1", "phone_session": snapshot["session"],
              "fiducial": target, "calibration_id": "factory-sha256-" + digest,
              "left": left, "right": right, "left_stream": left_stream, "right_stream": right_stream,
              "ring": str(ring), "capture_clock": "steam-frame-mono-v4l2",
              "clock_alignment": "unverified_no_imu_fusion", "record": bool(record)}
    (directory / "session.json").write_text(json.dumps(config, indent=2) + "\n")
    return config


def preview_pair(directory, message):
    slot = directory / ("preview-" + str(message["preview_slot"]))
    try:
        token = (slot / "token.json").read_bytes()
        if json.loads(token) != message["pair"]:
            return None
        images = [(slot / f"{v}.pgm").read_bytes() for v in range(2)]
        return images if (slot / "token.json").read_bytes() == token else None
    except (OSError, ValueError):
        return None


class FiducialPanel:
    def __init__(self, parent, app):
        import tkinter as tk
        from tkinter import ttk
        self.parent, self.app = parent, app
        self.process_lock = threading.Lock()
        self.process = None
        self.cancelled = threading.Event()
        self.events = queue.SimpleQueue()
        self.latest = queue.Queue(maxsize=1)
        self.closed = self.busy = False
        self.result = self.images = self.config = self.session = None
        self.last_update = 0
        self.status = tk.StringVar(value="Connect the phone, show its large marker, then Start tracking.")
        self.pose = tk.StringVar(value="No marker pose")
        self.record = tk.BooleanVar(value=False)
        panel = ttk.Frame(parent, padding=12)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Single-marker tracking", font=("sans", 20, "bold")).pack(anchor="w")
        ttk.Label(panel, text="One large tag36h11 marker, ID 0. Keep its whole black square and white margin visible.",
                  wraplength=900).pack(anchor="w", pady=6)
        setup = ttk.Frame(panel)
        setup.pack(fill="x")
        ttk.Button(setup, text="Enable cameras", command=app.enable_cameras).pack(side="left")
        ttk.Button(setup, text="Refresh cameras", command=app.refresh).pack(side="left", padx=6)
        ttk.Button(setup, text="Open results", command=lambda: app.open_folder(app.sessions)).pack(side="right")
        self.boxes = []
        mapping = ttk.Frame(panel)
        mapping.pack(fill="x", pady=8)
        for v, (name, factory, stream) in enumerate((("Front left", app.left, app.left_stream),
                                                   ("Front right", app.right, app.right_stream))):
            ttk.Label(mapping, text=name).grid(row=v, column=0, sticky="w")
            for col, variable, collection in ((1, factory, app.factory_boxes), (2, stream, app.stream_boxes)):
                box = ttk.Combobox(mapping, textvariable=variable, state="readonly", width=30)
                box.grid(row=v, column=col, padx=4)
                self.boxes.append(box)
                collection.append(box)
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=6)
        self.start_button = ttk.Button(actions, text="Start tracking", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(actions, text="Stop", command=self.stop).pack(side="left", padx=8)
        ttk.Checkbutton(panel, text="Record headset camera images + raw telemetry (512 MiB images / 32 MiB sensors max)",
                        variable=self.record).pack(anchor="w")
        ttk.Label(panel, text="The phone sizes its marker automatically. Android's reported display DPI sets an unverified distance scale.",
                  wraplength=900).pack(anchor="w", pady=4)
        self.canvases = []
        images = ttk.Frame(panel)
        images.pack(fill="both", expand=True, pady=8)
        images.rowconfigure(0, weight=1)
        for v in range(2):
            canvas = tk.Canvas(images, width=430, height=320, background="#151923", highlightthickness=0)
            canvas.grid(row=0, column=v, padx=4, sticky="nsew")
            images.columnconfigure(v, weight=1)
            self.canvases.append(canvas)
        ttk.Label(panel, textvariable=self.pose, font=("monospace", 12), wraplength=920).pack(anchor="w")
        ttk.Label(panel, textvariable=self.status, wraplength=920).pack(anchor="w", pady=4)
        self.timer = parent.after(50, self.tick)

    def start(self):
        if self.busy:
            return
        link = self.app.phone_panel.link
        try:
            snapshot = link.snapshot() if link else None
            selections = [var.get() for var in (self.app.left, self.app.right, self.app.left_stream, self.app.right_stream)]
            session = self.app.sessions / ("tag-" + uuid.uuid4().hex[:12])
            self.config = create_session(session, snapshot, getattr(self.app.runtime, "factory_root", Path("/")),
                                         selections, self.app.runtime.ring, self.record.get())
            self.session = session
            output = session / "run"
            recording = link.start_recording(session / "telemetry.jsonl") if self.config["record"] else None
            command = self.app.runtime.command("fiducial", "--session", session, "--track", "--output", output)
        except (OSError, ValueError, KeyError) as error:
            self.status.set(str(error))
            return
        self.cancelled.clear()
        try:
            self.latest.get_nowait()
        except queue.Empty:
            pass
        self.result = self.images = None
        self.redraw()
        self.busy = True
        self.last_update = time.monotonic()
        self.pose.set("Waiting for decoded markers")
        self.status.set(f"Reported black edge: {self.config['fiducial']['black_edge_m']*1000:.1f} mm. Searching both front views…")
        self.start_button.configure(state="disabled")
        for box in self.boxes:
            box.configure(state="disabled")
        def run():
            code, error = 1, ""
            try:
                with self.process_lock:
                    if self.cancelled.is_set():
                        return
                    self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                    text=True, errors="replace", bufsize=1)
                    process = self.process
                for line in process.stdout:
                    if line.startswith("{"):
                        message = json.loads(line)
                        images = preview_pair(output, message)
                        if images:
                            try:
                                self.latest.get_nowait()
                            except queue.Empty:
                                pass
                            self.latest.put_nowait((message, images))
                    else:
                        error = (error + line)[-4000:]
                code = process.wait()
            except (OSError, ValueError, KeyError) as exc:
                error = str(exc)
            finally:
                with self.process_lock:
                    if self.process:
                        if self.process.poll() is None:
                            self.process.kill()
                            self.process.wait()
                        self.process.stdout.close()
                    self.process = None
                if recording:
                    link.stop_recording()
                    if recording.error or recording.dropped:
                        error += f" Telemetry recording: {recording.error or 'queue full'}; dropped {recording.dropped}."
                self.events.put((code, error))
        threading.Thread(target=run, daemon=True).start()

    def redraw(self):
        import tkinter as tk
        for v, canvas in enumerate(self.canvases):
            canvas.delete("all")
            if not self.images:
                continue
            image = tk.PhotoImage(data=self.images[v], format="PPM")
            scale = max(1, math.ceil(image.width() / max(430, canvas.winfo_width())))
            canvas.image = image.subsample(scale)
            canvas.create_image(0, 0, image=canvas.image, anchor="nw")
            if not self.result:
                continue
            color = "#52e0a2" if self.result["status"] == "measured" else "#ffbd59"
            for tag in self.result["detections"][v]:
                points = tag["corners"]
                canvas.create_line(*[n/scale for p in points + [points[0]] for n in p], fill=color, width=2)
                canvas.create_text(points[0][0]/scale, points[0][1]/scale-12, anchor="sw", fill=color,
                                   text=f"ID {tag['id']} · margin {tag['margin']:.0f}")
            if self.result["status"] == "measured":
                for line in self.result["candidates"][0]["wireframe"][v]:
                    if len(line) > 1:
                        canvas.create_line(*[n/scale for p in line for n in p], fill=color, width=1)

    def show_result(self, result):
        self.result = result
        counts = [sum(t["id"] == 0 for t in view) for view in result["detections"]]
        self.status.set(f"ID 0 markers: left {counts[0]} · right {counts[1]} · "
                        f"processing {result['processing_ms']:.1f} ms · {result['reason'].replace('_', ' ')}")
        if result["status"] == "measured":
            best = result["candidates"][0]
            x, y, z = best["translation_m"]
            r = best["rotation"]
            angles = (math.degrees(math.atan2(r[3], r[0])), math.degrees(math.asin(max(-1, min(1, -r[6])))),
                      math.degrees(math.atan2(r[7], r[8])))
            self.pose.set(f"Marker center XYZ {x:+.3f}, {y:+.3f}, {z:+.3f} m · distance {math.sqrt(x*x+y*y+z*z):.3f} m (scale unverified)\n"
                          f"Z/Y/X angles {angles[0]:+.1f}°, {angles[1]:+.1f}°, {angles[2]:+.1f}° · RMS {best['rms_px']:.2f} px")
        else:
            self.pose.set(result["status"].capitalize() + " — no current pose")
        self.redraw()

    def stop(self):
        self.cancelled.set()
        with self.process_lock:
            process = self.process
            if process and process.poll() is None:
                process.terminate()
                def reap():
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                threading.Thread(target=reap, daemon=True).start()
        self.result = None
        self.pose.set("Stopped — no current pose")
        self.status.set("Stopped. Start tracking to search again.")
        self.redraw()

    def tick(self):
        try:
            result, images = self.latest.get_nowait()
            if not self.cancelled.is_set():
                self.images = images
                self.last_update = time.monotonic()
                self.show_result(result)
        except queue.Empty:
            pass
        if self.busy and not self.cancelled.is_set():
            link = self.app.phone_panel.link
            snapshot = link.snapshot() if link else None
            if (not snapshot or snapshot["session"] != self.config["phone_session"] or
                    snapshot.get("fiducial") != self.config["fiducial"]):
                self.stop()
                self.status.set("Phone disconnected or marker profile changed. Reconnect and start again.")
            elif time.monotonic() - self.last_update > 1:
                self.result = None
                self.pose.set("Stale — no current pose")
                self.redraw()
        try:
            code, error = self.events.get_nowait()
            self.busy = False
            self.result = None
            self.pose.set("Stopped — no current pose")
            if error.strip():
                self.status.set(error.strip())
            elif not self.cancelled.is_set():
                self.status.set(f"Tracker finished (status {code}). Start tracking to retry.")
            self.start_button.configure(state="normal")
            for box in self.boxes:
                box.configure(state="readonly")
            self.redraw()
        except queue.Empty:
            pass
        if not self.closed:
            self.timer = self.parent.after(50, self.tick)

    def close(self):
        self.closed = True
        self.parent.after_cancel(self.timer)
        self.stop()

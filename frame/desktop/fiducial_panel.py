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

from camera_image import fit_image
from phone_link import validate_fiducial
from ring_preview import preview

REJECTION_HINTS = {
    "tag0_not_visible_in_both_front_cameras": "Keep the whole marker and white border visible in both front cameras.",
    "multiple_tag0_detections": "More than one usable ID 0 was seen. Leave only the phone marker visible.",
    "invalid_or_too_small_front_corners": "The marker corners are too small or invalid. Try closer, with less glare.",
    "stereo_reprojection_failed": "The stereo geometry disagrees. Verify physical camera/calibration mapping and marker scale.",
    "competing_pose_hypotheses": "The orientation is ambiguous. Hold still and tilt the phone slightly.",
}


def create_session(directory, snapshot, factory_root, selections, ring, record):
    if not snapshot:
        raise ValueError("Connect your phone in Phone telemetry first.")
    if snapshot.get("marker_displayed") is False:
        raise ValueError("Show the fullscreen tracking marker on the phone first.")
    if snapshot.get("marker_displayed") is True and not snapshot.get("marker_state_fresh"):
        raise ValueError("Waiting for the phone's current fullscreen marker state.")
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
    if "dimensions" in snapshot:
        config["thickness_m"] = snapshot["dimensions"][2]
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
        self.raw_images = [None, None]
        self.raw_detections = [[], []]
        self.raw_updated = [0, 0]
        self.camera_status = [tk.StringVar(value=name + " — select/enable camera") for name in ("Front left", "Front right")]
        self.last_update = 0
        self.has_results = False
        self.status = tk.StringVar(value="Connect the phone, show its large marker, then Start tracking.")
        self.pose = tk.StringVar(value="No marker pose")
        self.record = tk.BooleanVar(value=False)
        self.vr_enabled = tk.BooleanVar(value=False)
        self.vr_status = tk.StringVar(value="VR test off. Distance scale and headset alignment are unverified.")
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
        mapping.pack(fill="x", pady=4)
        mapping.columnconfigure((1, 2), weight=1, uniform="camera-selection")
        ttk.Label(mapping, text="Factory calibration").grid(row=0, column=1, sticky="w")
        ttk.Label(mapping, text="Camera stream").grid(row=0, column=2, sticky="w")
        for v, (name, factory, stream) in enumerate((("Front left", app.left, app.left_stream),
                                                   ("Front right", app.right, app.right_stream))):
            ttk.Label(mapping, text=name).grid(row=v+1, column=0, sticky="w")
            for col, variable, collection in ((1, factory, app.factory_boxes), (2, stream, app.stream_boxes)):
                box = ttk.Combobox(mapping, textvariable=variable, state="readonly", width=1)
                box.grid(row=v+1, column=col, padx=4, sticky="ew")
                self.boxes.append(box)
                collection.append(box)
        actions = setup
        self.start_button = ttk.Button(actions, text="Start tracking", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(actions, text="Stop", command=self.stop).pack(side="left", padx=8)
        options = ttk.Frame(panel)
        options.pack(fill="x", pady=4)
        ttk.Checkbutton(options, text="Record cameras + telemetry", variable=self.record).pack(side="left")
        ttk.Checkbutton(options, text="Show tracked screen in VR (SteamVR)", variable=self.vr_enabled,
                        command=self.toggle_vr).pack(side="left", padx=8)
        ttk.Label(panel, textvariable=self.vr_status, wraplength=650).pack(anchor="w")
        self.pose_label = ttk.Label(panel, textvariable=self.pose, font=("monospace", 11), wraplength=650)
        self.pose_label.pack(anchor="w")
        ttk.Label(panel, textvariable=self.status, wraplength=650).pack(anchor="w", pady=4)
        self.canvases = []
        images = ttk.Frame(panel)
        images.pack(fill="both", expand=True, pady=8)
        images.rowconfigure(0, weight=1)
        for v in range(2):
            view = ttk.Frame(images)
            view.grid(row=0, column=v, padx=4, sticky="nsew")
            ttk.Label(view, textvariable=self.camera_status[v], wraplength=300).pack(fill="x")
            canvas = tk.Canvas(view, width=1, height=1, background="#151923", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Configure>", lambda _event: self.redraw())
            images.columnconfigure(v, weight=1)
            self.canvases.append(canvas)
        self.timer = parent.after(50, self.tick)

    def start(self):
        if self.busy:
            return
        link = self.app.phone_panel.link
        try:
            snapshot = link.snapshot() if link else None
            if not snapshot:
                raise ValueError("Connect your phone in Phone telemetry first.")
            selections = [var.get() for var in (self.app.left, self.app.right, self.app.left_stream, self.app.right_stream)]
            if not all(selections) or selections[2] == selections[3]:
                raise ValueError("Choose two distinct front camera streams and matching calibrations.")
            for v, (stream, calibration) in enumerate(zip(selections[2:], selections[:2])):
                side = ("Front left", "Front right")[v]
                try:
                    current = preview(self.app.runtime.ring, stream, metadata=True)
                    if current is None:
                        raise ValueError("no frame received; wait for the broker or choose the correct stream")
                    width, height, _, metadata = current
                    published = metadata["publish_monotonic_ns"]
                    if published and not 0 <= time.monotonic_ns()-published <= 1_000_000_000:
                        raise ValueError("camera frames are stale")
                    factory = self.app.factories.get(calibration)
                    if factory and (width, height) != (factory["width"], factory["height"]):
                        raise ValueError(f"{width}×{height} stream differs from {calibration} calibration size")
                except (OSError, ValueError) as error:
                    raise ValueError(f"{side} ({stream}): {error}. Stereo pose needs both front cameras.") from error
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
        self.has_results = False
        self.publish_vr(None)
        self.toggle_vr()
        self.last_update = time.monotonic()
        self.pose.set("Waiting for decoded markers")
        self.status.set(f"Reported black edge: {self.config['fiducial']['black_edge_m']*1000:.1f} mm. Searching both front views…")
        self.start_button.configure(state="disabled")
        for box in self.boxes:
            box.configure(state="disabled")
        def run():
            code, error = 1, ""
            try:
                with (session / "tracker.log").open("w", buffering=1) as logfile:
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
                            try:
                                self.latest.get_nowait()
                            except queue.Empty:
                                pass
                            # Pose delivery must not depend on racing preview slots.
                            self.latest.put_nowait((message, images))
                        else:
                            logfile.write(line)
                            self.events.put(("log", line.rstrip()))
                            error = (error + line)[-4000:]
                    code = process.wait()
                    logfile.write(f"Tracker exited with status {code}\n")
            except (OSError, ValueError, KeyError) as exc:
                error = str(exc)
                self.events.put(("log", error))
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
                self.events.put(("exit", (code, error)))
        threading.Thread(target=run, daemon=True).start()

    def publish_vr(self, result):
        if self.session is None:
            return
        message = {"status": "lost"}
        if result and result["status"] == "measured":
            message = {key: result[key] for key in ("schema", "transform", "status", "processed_host_monotonic_ns")}
            message["candidates"] = [{key: result["candidates"][0][key] for key in ("rotation", "translation_m")}]
        try:
            temporary = self.session / "vr-pose.json.tmp"
            temporary.write_text(json.dumps(message, allow_nan=False) + "\n")
            temporary.replace(self.session / "vr-pose.json")
        except (OSError, ValueError, KeyError) as error:
            self.vr_status.set("Cannot publish VR pose: " + str(error))
            self.app.terminate("overlay")

    def toggle_vr(self):
        if not self.vr_enabled.get() or not self.busy or self.cancelled.is_set():
            self.publish_vr(None)
            self.app.terminate("overlay")
            self.vr_status.set("VR test display is off.")
            return
        if "overlay" not in self.app.processes:
            if self.app.spawn("overlay", self.app.runtime.command("overlay", "--session", self.session)):
                self.vr_status.set("Opening VR test display. Details appear in Camera setup log.")
            else:
                self.vr_status.set("Cannot start VR display. Optical tracking remains available.")

    def redraw(self):
        import tkinter as tk
        for v, canvas in enumerate(self.canvases):
            canvas.delete("all")
            paired = self.result is not None and self.images is not None
            data = self.images[v] if paired else self.raw_images[v] if time.monotonic()-self.raw_updated[v] < 1 else None
            if data is None:
                canvas.image = None
                canvas.create_text(12, 12, anchor="nw", fill="#eeeeee", text="Waiting for this camera…")
                continue
            canvas.image, scale, offset = fit_image(data, canvas.winfo_width(), canvas.winfo_height())
            canvas.create_image(*offset, image=canvas.image, anchor="nw")
            def point(p):
                return [p[k]*scale[k]+offset[k] for k in range(2)]
            if not paired:
                continue
            color = "#52e0a2" if self.result["status"] == "measured" else "#ffbd59"
            for tag in self.result["detections"][v]:
                points = tag["corners"]
                canvas.create_line(*[n for p in points + [points[0]] for n in point(p)], fill=color, width=2, tags="tag-detection")
                canvas.create_text(point(points[0])[0], point(points[0])[1]-12, anchor="sw", fill=color,
                                   text=f"ID {tag['id']} · margin {tag['margin']:.0f}")
                center = point([sum(p[k] for p in points)/4 for k in range(2)])
                canvas.create_oval(center[0]-3, center[1]-3, center[0]+3, center[1]+3,
                                   fill=color, outline=color, tags="tag-center")
            if self.result["status"] == "measured":
                for line in self.result["candidates"][0]["wireframe"][v]:
                    if len(line) > 1:
                        canvas.create_line(*[n for p in line for n in point(p)], fill=color, width=1)
                for name, axis_color, line in zip(("X", "Y", "Z"), ("#ff6868", "#52e0a2", "#71b7ff"),
                                                  self.result["candidates"][0].get("axes", [[], []])[v]):
                    if len(line) > 1:
                        canvas.create_line(*[n for p in line for n in point(p)], fill=axis_color, width=3,
                                           arrow="last", tags="pose-axis")
                        canvas.create_text(*point(line[-1]), anchor="sw", fill=axis_color, text=name)

    def camera_preview(self, view, stream, current, error):
        side = ("Front left", "Front right")[view]
        if current:
            width, height, data, metadata = current
            self.raw_images[view] = data
            self.raw_detections[view] = metadata.get("detections", [])
            self.raw_updated[view] = time.monotonic()
            count = sum(tag["id"] == 0 for tag in metadata.get("detections", []))
            state = metadata.get("frame_status", "")
            if state == "raw":
                mode = f"Raw available frame {metadata['sequence']} · no annotations"
            elif state == "paused":
                mode = f"Paused · last annotated frame {metadata['sequence']}"
            else:
                mode = f"tracking pair {self.result['pair']}" if self.result is not None and self.images is not None else f"preview · ID 0 markers: {count} (2D)"
            if metadata.get("publication_warning"):
                mode += " · " + metadata["publication_warning"]
            if metadata.get("counters"):
                mode += "\n" + metadata["counters"]
            self.camera_status[view].set(f"{side} · {stream} · {width}×{height}\n{mode}")
        else:
            self.raw_images[view] = None
            self.raw_detections[view] = []
            self.camera_status[view].set(f"{side} · {stream or 'not selected'}\n{error}")
        if self.parent.winfo_ismapped() and (self.result is None or self.images is None):
            self.redraw()

    def show_result(self, result):
        self.result = result
        self.publish_vr(result)
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
            self.pose.set(result["status"].capitalize() + " — no current 3D pose\n" +
                          REJECTION_HINTS.get(result["reason"], result["reason"].replace("_", " ")))
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
        self.publish_vr(None)
        self.app.terminate("overlay")
        self.pose.set("Stopped — no current pose")
        self.status.set("Stopped. Start tracking to search again.")
        self.redraw()

    def tick(self):
        try:
            result, images = self.latest.get_nowait()
            if not self.cancelled.is_set():
                self.images = images
                self.has_results = True
                self.last_update = time.monotonic()
                self.show_result(result)
        except queue.Empty:
            pass
        if self.busy and not self.cancelled.is_set():
            link = self.app.phone_panel.link
            snapshot = link.snapshot() if link else None
            if (not snapshot or snapshot["session"] != self.config["phone_session"] or
                    snapshot.get("fiducial") != self.config["fiducial"] or
                    snapshot.get("marker_displayed") is False or
                    (snapshot.get("marker_displayed") is True and not snapshot.get("marker_state_fresh"))):
                self.stop()
                self.status.set("Phone disconnected, marker hidden, or marker geometry changed. Show the marker and start again.")
            elif time.monotonic() - self.last_update > 1:
                self.result = None
                self.images = None
                self.publish_vr(None)
                self.pose.set("Stale — no current pose" if self.has_results else
                              "Waiting for a synchronized stereo pair — no 3D pose yet")
                self.redraw()
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.app.log("[marker] " + value)
                if value.startswith("Stereo waiting:") and self.result is None and not self.cancelled.is_set():
                    self.status.set(value)
                continue
            code, error = value
            self.app.log(f"[marker] Tracker exited with status {code}; results: {self.session}")
            self.busy = False
            self.result = None
            self.publish_vr(None)
            self.app.terminate("overlay")
            self.pose.set("Stopped — no current pose")
            if code and not self.cancelled.is_set():
                self.status.set(f"Tracker failed (exit {code}): {error.strip()} · See tracker.log in Open results.")
            elif not self.cancelled.is_set():
                self.status.set(f"Tracker finished (status {code}). Start tracking to retry.")
            self.start_button.configure(state="normal")
            for box in self.boxes:
                box.configure(state="readonly")
            self.redraw()
        if not self.closed:
            self.timer = self.parent.after(50, self.tick)

    def close(self):
        self.closed = True
        self.parent.after_cancel(self.timer)
        self.stop()

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
from pose_stream import PoseStream

REJECTION_HINTS = {
    "tag0_not_visible_in_both_front_cameras": "Keep the whole marker and white border visible in both front cameras.",
    "multiple_tag0_detections": "More than one usable ID 0 was seen. Leave only the phone marker visible.",
    "invalid_or_too_small_front_corners": "The marker corners are too small or invalid. Try closer, with less glare.",
    "stereo_reprojection_failed": "The stereo geometry disagrees. Verify physical camera/calibration mapping and marker scale.",
    "competing_pose_hypotheses": "The orientation is ambiguous. Hold still and tilt the phone slightly.",
}


def create_session(directory, snapshot, factory_root, selections, ring, record, arcore_handoff=False):
    if not snapshot:
        raise ValueError("Connect your phone first.")
    if snapshot.get("marker_displayed") is False:
        raise ValueError("Show the fullscreen tracking marker on the phone first.")
    if snapshot.get("marker_displayed") is True and not snapshot.get("marker_state_fresh"):
        raise ValueError("Waiting for the phone's current fullscreen marker state.")
    target = validate_fiducial(snapshot.get("fiducial"))
    if target is None:
        raise ValueError("Update the Android app and reconnect. A valid automatic marker profile is required.")
    if arcore_handoff and snapshot.get("arcore") is None:
        raise ValueError("Update the phone app and start ARCore before handoff tracking.")
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
    if arcore_handoff:
        config["arcore_handoff"] = True
        config["clock_alignment"] = "stationary_update_time_prototype"
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
        self.vr_write_lock = threading.Lock()
        self.process = None
        self.cancelled = threading.Event()
        self.events = queue.SimpleQueue()
        self.latest = queue.Queue(maxsize=1)
        self.closed = self.busy = False
        self.result = self.images = self.config = self.session = None
        self.preview_images = [None, None]
        self.preview_detections = [[], []]
        self.preview_updated = [0, 0]
        self.camera_status = [tk.StringVar(value=name + " — starting camera") for name in ("Front left", "Front right")]
        self.last_update = 0
        self.has_results = False
        self.status = tk.StringVar(value="Tracking starts automatically when the phone marker appears.")
        self.pose = tk.StringVar(value="No marker pose")
        self.record = tk.BooleanVar(value=False)
        self.handoff_active = False
        self.last_arcore_command = 0
        self.last_arcore_command_key = None
        self.auto_last_attempt = 0
        self.retry_after = 0
        self.retry_delay = .5
        self.retry_acquisition = None
        self.vr_retry_after = 0
        self.vr_retry_delay = .5
        self.pose_stream = None
        self.vr_status = tk.StringVar(value="VR display starts automatically with tracking.")
        panel = ttk.Frame(parent, padding=(0, 6))
        panel.pack(fill="both", expand=True)
        setup = ttk.Frame(panel)
        setup.pack(fill="x", pady=4)
        app.camera_button = ttk.Button(setup, text="Retry cameras", command=app.enable_cameras)
        app.camera_button.pack(side="left")
        ttk.Button(setup, text="Activity log", command=app.toggle_log).pack(side="right")
        ttk.Button(setup, text="Open results", command=lambda: app.open_folder(app.sessions)).pack(side="right", padx=6)
        options = ttk.Frame(panel)
        options.pack(fill="x", pady=4)
        ttk.Checkbutton(options, text="Record cameras + telemetry", variable=self.record).pack(side="left")
        ttk.Label(panel, textvariable=self.vr_status, wraplength=650).pack(anchor="w")
        self.pose_label = ttk.Label(panel, textvariable=self.pose, font=("monospace", 11), wraplength=650)
        self.pose_label.pack(anchor="w")
        ttk.Label(panel, textvariable=self.status, wraplength=650).pack(anchor="w", pady=4)
        ttk.Checkbutton(panel, text="Show camera views", variable=app.show_views,
                        command=app.toggle_views).pack(anchor="w")
        self.canvases = []
        self.image_panel = images = ttk.Frame(panel)
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
        self.set_camera_views(app.show_views.get())
        self.timer = parent.after(50, self.tick)

    def start(self):
        if self.busy:
            return
        if "overlay" in self.app.stopping:
            return  # Wait for the old renderer's exit before a recovery restart.
        link = self.app.phone_panel.link
        try:
            snapshot = link.snapshot() if link else None
            if not snapshot:
                raise ValueError("Connect your phone first.")
            selections = self.app.camera_selection
            for v, (stream, calibration) in enumerate(zip(selections[2:], selections[:2])):
                side = ("Front left", "Front right")[v]
                try:
                    current = preview(self.app.runtime.ring, stream, metadata=True)
                    if current is None:
                        raise ValueError("no frame received; wait for camera startup or retry cameras")
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
                                         selections, self.app.runtime.ring, self.record.get(), snapshot.get("arcore") is not None)
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
        if self.config.get("arcore_handoff"):
            self.pose_stream = PoseStream(session / "phone-pose.json", link.pose_packet, self.config["phone_session"])
        self.handoff_active = False
        self.has_results = False
        self.publish_vr(None)
        self.ensure_vr()
        self.last_update = time.monotonic()
        self.pose.set("Waiting for decoded markers")
        self.status.set(f"Reported black edge: {self.config['fiducial']['black_edge_m']*1000:.1f} mm. Searching both front views…")
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
                            self.write_vr(message)
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

    def write_vr(self, result):
        """Atomic pose publication used directly by the tracker reader thread."""
        if self.session is None:
            return
        message = {"status": "lost"}
        if result and result["status"] == "measured":
            message = {key: result[key] for key in ("schema", "transform", "status", "processed_host_monotonic_ns")}
            message["candidates"] = [{key: result["candidates"][0][key] for key in ("rotation", "translation_m")}]
            if "observed_host_monotonic_ns" in result:
                message["observed_host_monotonic_ns"] = result["observed_host_monotonic_ns"]
                message["candidates"][0]["rms_px"] = result["candidates"][0]["rms_px"]
        # UI stop and a final detector result can overlap. Serialize replacement.
        with self.vr_write_lock:
            temporary = self.session / "vr-pose.json.tmp"
            temporary.write_text(json.dumps(message, allow_nan=False) + "\n")
            temporary.replace(self.session / "vr-pose.json")

    def publish_vr(self, result):
        if self.session is None:
            return
        try:
            self.write_vr(result)
        except (OSError, ValueError, KeyError) as error:
            self.vr_status.set("Cannot publish VR pose: " + str(error))
            self.app.terminate("overlay")

    def ensure_vr(self):
        if not self.busy or self.cancelled.is_set():
            return
        now = time.monotonic()
        if "overlay" not in self.app.processes and "overlay" not in self.app.stopping and now >= self.vr_retry_after:
            self.vr_retry_after = now + self.vr_retry_delay
            self.vr_retry_delay = min(5., self.vr_retry_delay * 2)
            try:
                (self.session / "arcore-state.json").unlink(missing_ok=True)
            except OSError as error:
                self.vr_status.set("Cannot reset VR status: " + str(error))
                return
            if self.app.spawn("overlay", self.app.runtime.command("overlay", "--session", self.session)):
                self.vr_status.set("Opening VR display. Details appear in the activity log.")
            else:
                self.vr_status.set("Cannot start VR display. Optical tracking remains available.")

    def redraw(self):
        for v, canvas in enumerate(self.canvases):
            canvas.delete("all")
            paired = self.result is not None and self.images is not None
            data = self.images[v] if paired else self.preview_images[v] if time.monotonic()-self.preview_updated[v] < 1 else None
            if data is None:
                canvas.image = None
                canvas.create_text(12, 12, anchor="nw", fill="#eeeeee",
                                   text="Optical detection paused — ARCore tracking" if self.handoff_active else "Waiting for this camera…")
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

    def set_camera_views(self, visible):
        if visible:
            self.image_panel.pack(fill="both", expand=True, pady=8)
        else:
            self.image_panel.pack_forget()

    @staticmethod
    def rate_caption(metadata):
        rates = metadata.get("rates", {})
        return (f" · camera {rates['capture_hz']:.0f} / detect {rates['detection_hz']:.0f} Hz"
                if rates.get("capture_hz", 0) > 0 else "")

    def camera_preview(self, view, current, error):
        side = ("Front left", "Front right")[view]
        if current:
            width, height, data, metadata = current
            self.preview_images[view] = data
            self.preview_detections[view] = metadata.get("detections", [])
            self.preview_updated[view] = time.monotonic()
            count = sum(tag["id"] == 0 for tag in self.preview_detections[view])
            self.camera_status[view].set(f"{side} · {width}×{height} · ID 0: {count}" + self.rate_caption(metadata))
        else:
            self.preview_images[view] = None
            self.preview_detections[view] = []
            self.camera_status[view].set(f"{side} · {error}")
        if self.parent.winfo_ismapped() and (self.result is None or self.images is None):
            self.redraw()

    def show_result(self, result):
        self.result = result
        counts = [sum(t["id"] == 0 for t in view) for view in result["detections"]]
        for view, frame in enumerate(result["frames"]):
            side = ("Front left", "Front right")[view]
            self.camera_status[view].set(f"{side} · {frame['width']}×{frame['height']} · ID 0: {counts[view]}" + self.rate_caption(frame))
        self.status.set(f"ID 0 markers: left {counts[0]} · right {counts[1]}")
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
        if self.pose_stream:
            self.pose_stream.close()
            self.pose_stream = None
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
        self.handoff_active = False
        self.publish_vr(None)
        self.app.terminate("overlay")
        self.pose.set("Stopped — no current pose")
        self.status.set("Waiting for the connected phone marker.")
        self.redraw()

    def update_arcore(self, link, snapshot):
        """Bridge validated phone poses and native handoff state; never solve in Tk."""
        packet = snapshot.get("arcore")
        if packet is None:
            self.stop()
            self.status.set("ARCore extension unavailable. Update and reconnect the phone.")
            return
        try:
            if self.pose_stream and self.pose_stream.error:
                raise ValueError(self.pose_stream.error)
            state = {}
            path = self.session / "arcore-state.json"
            if path.exists() and path.stat().st_size <= 65536:
                state = json.loads(path.read_text())
            latest = packet["poses"][-1] if packet["poses"] else {}
            acquisition = (latest.get("generation"), latest.get("acquisition"))
            renderer = self.app.processes.get("overlay")
            renderer_alive = (renderer is not None and renderer.poll() is None and "overlay" not in self.app.stopping)
            if not renderer_alive:
                state = {}  # A previous process heartbeat cannot acknowledge its replacement.
                self.ensure_vr()
                renderer = self.app.processes.get("overlay")
                renderer_alive = (renderer is not None and renderer.poll() is None and "overlay" not in self.app.stopping)
            current = (state.get("generation") == latest.get("generation") and
                       state.get("acquisition") == latest.get("acquisition") and
                       0 <= time.monotonic_ns()-state.get("updated_host_monotonic_ns", 0) < 500_000_000 and
                       renderer_alive)
            accepted = current and state.get("state") == "tracking" and state.get("visible") is True
            paused = (accepted or not snapshot.get("marker_displayed") or
                      not snapshot.get("marker_state_fresh"))
            gate = self.session / "optical-paused"
            if paused and not gate.exists():
                gate.touch()
            elif not paused:
                gate.unlink(missing_ok=True)
            kind = ("alignment_accepted" if accepted and latest.get("marker_required") else
                    "alignment_lost" if not accepted and not latest.get("marker_required") else None)
            command_key = (kind, *acquisition)
            if latest and kind and (command_key != self.last_arcore_command_key or
                                    time.monotonic()-self.last_arcore_command >= .5):
                if link.alignment_command(kind, latest["generation"], latest["acquisition"]):
                    self.last_arcore_command = time.monotonic()
                    self.last_arcore_command_key = command_key
            if accepted != self.handoff_active:
                self.handoff_active = accepted
                self.result = self.images = None
                if accepted:
                    self.preview_images = [None, None]
                    self.preview_detections = [[], []]
                    for view, side in enumerate(("Front left", "Front right")):
                        self.camera_status[view].set(side + " · optical detection paused")
                self.redraw()
            if accepted:
                self.vr_retry_delay = .5
                metrics = (f"ARCore {state.get('source_hz', state['pose_hz']):.0f} / received {state['pose_hz']:.0f} Hz · render {state['render_hz']:.0f} Hz · "
                           f"pose age ≈ {state['pose_age_ms']:.0f} ms · prediction {state['prediction_ms']:.0f} ms"
                           if "pose_hz" in state else "ARCore world pose · optical detection paused")
                self.pose.set(metrics)
                self.status.set("Tracking from phone. Optical detection paused.")
            elif latest.get("reason") in ("user_dismissed", "headset_not_worn"):
                self.pose.set("Tracking paused")
                self.status.set("Paused until next phone unlock." if latest["reason"] == "user_dismissed"
                                else "Put on the headset to resume tracking.")
            elif latest.get("state") in ("error", "stopped"):
                self.pose.set("ARCore unavailable — no current VR pose")
                self.status.set("Open the phone app and restart ARCore. " + latest.get("reason", ""))
            elif latest.get("marker_required") and not snapshot.get("marker_displayed"):
                self.pose.set("Alignment required — no current VR pose")
                self.status.set("Waiting for the phone's automatic marker overlay.")
            elif latest.get("state") == "paused":
                self.status.set("Marker acquisition active · phone ARCore: " + latest.get("reason", "resuming"))
            else:
                self.status.set("ARCore: " + state.get("reason", "waiting for VR display and phone poses"))
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.stop()
            self.status.set("ARCore handoff failed: " + str(error))

    def tick(self):
        link = self.app.phone_panel.link
        snapshot = link.snapshot() if link else None
        poses = (snapshot.get("arcore") or {}).get("poses", []) if snapshot else []
        acquisition = ((snapshot["session"], poses[-1]["generation"] if poses else None,
                        poses[-1]["acquisition"] if poses else None) if snapshot else None)
        if acquisition != self.retry_acquisition:
            self.retry_acquisition = acquisition
            self.retry_after = 0
            self.retry_delay = .5
            self.vr_retry_after = 0
            self.vr_retry_delay = .5
        # A native worker may exit after handoff while the phone marker is hidden.
        # Request a fresh acquisition so recovery cannot wait on an invisible tag.
        latest = poses[-1] if poses else {}
        if (not self.busy and latest and not latest.get("marker_required", True) and
                time.monotonic()-self.last_arcore_command >= .5):
            if link.alignment_command("alignment_lost", latest["generation"], latest["acquisition"]):
                self.last_arcore_command = time.monotonic()
        if (not self.busy and snapshot and snapshot.get("automatic_marker") and
                snapshot.get("marker_displayed") and snapshot.get("marker_state_fresh") and
                time.monotonic() >= self.retry_after and
                time.monotonic()-self.auto_last_attempt >= .25):
            self.auto_last_attempt = time.monotonic()
            self.start()
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
            if (not snapshot or snapshot["session"] != self.config["phone_session"] or
                    snapshot.get("fiducial") != self.config["fiducial"] or
                    (not self.config.get("arcore_handoff") and
                     (snapshot.get("marker_displayed") is False or
                      (snapshot.get("marker_displayed") is True and not snapshot.get("marker_state_fresh"))))):
                self.stop()
                self.status.set("Phone disconnected, marker hidden, or marker geometry changed. Tracking resumes automatically when ready.")
            elif self.config.get("arcore_handoff"):
                self.update_arcore(link, snapshot)
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
            if self.pose_stream:
                self.pose_stream.close()
                self.pose_stream = None
            self.result = None
            self.publish_vr(None)
            self.app.terminate("overlay")
            self.pose.set("Stopped — no current pose")
            if code and not self.cancelled.is_set():
                self.retry_after = time.monotonic() + self.retry_delay
                self.retry_delay = min(5., self.retry_delay * 2)
                detail = error.strip().splitlines()[-1] if error.strip() else "No error details"
                self.status.set(f"Tracker failed (exit {code}): {detail} · See tracker.log in Open results.")
            elif not self.cancelled.is_set():
                self.status.set(f"Tracker finished (status {code}). Retrying automatically.")
            self.redraw()
        if not self.closed:
            self.timer = self.parent.after(50, self.tick)

    def close(self):
        self.closed = True
        self.parent.after_cancel(self.timer)
        self.stop()

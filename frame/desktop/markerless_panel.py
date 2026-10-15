"""Desktop workflow for labelled stereo geometry and local outline tracking."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_session(directory, snapshot, factory_root, selections, ring, record):
    """Freeze authenticated dimensions and the exact calibration bytes for replay."""
    if not snapshot:
        raise ValueError("Connect your phone in Phone telemetry first.")
    left, right, left_stream, right_stream = selections
    if not all(selections) or left == right or left_stream == right_stream:
        raise ValueError("Choose two distinct front cameras and their matching calibrations.")
    dimensions = snapshot["dimensions"]
    w, h, d = dimensions
    if not all(math.isfinite(x) for x in dimensions) or not (.02 <= w <= .5 and w <= h <= .8 and .001 <= d <= .1):
        raise ValueError("Invalid phone body dimensions")
    calibration = [(name, (factory_root / "persist" / name).read_bytes())
                   for name in ("xrservice.json", "device_config.json")]
    digest = hashlib.sha256(b"".join(data for _, data in calibration)).hexdigest()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    destination = directory / "factory/persist"
    destination.mkdir(parents=True)
    for name, data in calibration:
        (destination / name).write_bytes(data)
    config = {"schema": "framephone-markerless-session-v1",
              "phone_session": snapshot["session"],
              "phone_body": dict(zip(("width_m", "height_m", "thickness_m"), dimensions)),
              "body_axes": "centered_right_top_front", "boundary": "body_or_case",
              "calibration_id": "factory-sha256-" + digest,
              "left": left, "right": right, "left_stream": left_stream, "right_stream": right_stream,
              "ring": str(ring), "capture_clock": "steam-frame-mono-v4l2",
              "clock_alignment": "unverified_no_imu_fusion", "record": bool(record)}
    write_json(directory / "session.json", config)
    return config


def preview_pair(directory, message):
    """Return only images belonging to this exact native result, or skip a race."""
    slot = directory / ("preview-" + str(message["preview_slot"]))
    try:
        token = (slot / "token.json").read_bytes()
        if json.loads(token) != message["pair"]:
            return None
        images = [(slot / f"{view}.pgm").read_bytes() for view in range(2)]
        if (slot / "token.json").read_bytes() != token:
            return None
        return images
    except (OSError, ValueError):
        return None


class MarkerlessPanel:
    def __init__(self, parent, app):
        import tkinter as tk
        from tkinter import ttk
        self.parent, self.app = parent, app
        self.events = queue.SimpleQueue()
        self.latest = queue.Queue(maxsize=1)
        self.process_lock = threading.Lock()
        self.process = None
        self.cancelled = threading.Event()
        self.closed = self.busy = self.live = False
        self.session = self.config = self.capture = self.result = None
        self.corners = [[], []]
        self.images = self.initial_images = None
        self.last_update = 0
        self.status = tk.StringVar(value="Connect your phone, enable the front cameras, then capture a pair.")
        self.pose = tk.StringVar(value="No body pose")
        self.record = tk.BooleanVar(value=False)
        self.labelled = tk.BooleanVar(value=False)
        panel = ttk.Frame(parent, padding=12)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Markerless phone tracking", font=("sans", 20, "bold")).pack(anchor="w")
        ttk.Label(panel, text="First optical baseline: a clear front outline in both cameras. Hold the phone still during setup.",
                  wraplength=900).pack(anchor="w", pady=6)
        setup = ttk.Frame(panel)
        setup.pack(fill="x")
        ttk.Button(setup, text="Enable cameras", command=app.enable_cameras).pack(side="left")
        ttk.Button(setup, text="Refresh cameras", command=app.refresh).pack(side="left", padx=6)
        ttk.Button(setup, text="Open results", command=lambda: app.open_folder(app.sessions)).pack(side="right")
        mapping = ttk.Frame(panel)
        mapping.pack(fill="x", pady=6)
        self.boxes = []
        for v, (label, factory, stream) in enumerate((("Front left", app.left, app.left_stream),
                                                    ("Front right", app.right, app.right_stream))):
            ttk.Label(mapping, text=label).grid(row=v, column=0, sticky="w")
            for col, var, collection in ((1, factory, app.factory_boxes), (2, stream, app.stream_boxes)):
                box = ttk.Combobox(mapping, textvariable=var, state="readonly", width=30)
                box.grid(row=v, column=col, padx=4, sticky="ew")
                collection.append(box)
                self.boxes.append(box)
        ttk.Label(panel, text="Verify the front lenses and calibration mapping. Pairing alone does not identify the phone in the image.",
                  wraplength=900).pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=8)
        self.capture_button = ttk.Button(actions, text="1. Capture pair", command=self.freeze)
        self.capture_button.pack(side="left")
        self.solve_button = ttk.Button(actions, text="2. Estimate pose", command=self.solve, state="disabled")
        self.solve_button.pack(side="left", padx=6)
        self.track_button = ttk.Button(actions, text="3. Track outline", command=self.track, state="disabled")
        self.track_button.pack(side="left")
        ttk.Button(actions, text="Stop", command=self.stop).pack(side="left", padx=6)
        self.open_button = ttk.Button(actions, text="Open trial…", command=self.open_trial)
        self.open_button.pack(side="right")
        self.replay_button = ttk.Button(actions, text="Replay images…", command=self.replay, state="disabled")
        self.replay_button.pack(side="right", padx=6)
        ttk.Checkbutton(panel, text="Record live trial images + raw phone telemetry (up to 512 MiB images / 32 MiB sensors)",
                        variable=self.record).pack(anchor="w")
        ttk.Checkbutton(panel, text="I can identify this phone's physical top and front face in both views",
                        variable=self.labelled, command=self.invalidate).pack(anchor="w", pady=5)
        self.instructions = ttk.Label(panel, wraplength=900,
            text="In EACH frozen view click the body's top-left → top-right → bottom-right → bottom-left. "
                 "Use the outer front rim, not the lit screen. Right-click undoes a point; use Open full-size for precise clicks.")
        self.instructions.pack(anchor="w")
        images = ttk.Frame(panel)
        images.pack(fill="both", expand=True, pady=6)
        self.canvases, self.scales = [], [1, 1]
        for view in range(2):
            canvas = tk.Canvas(images, width=430, height=320, background="#151923", highlightthickness=0)
            canvas.grid(row=0, column=view, padx=4, sticky="nsew")
            images.columnconfigure(view, weight=1)
            canvas.bind("<Button-1>", lambda event, v=view: self.click(v, event.x, event.y))
            canvas.bind("<Button-3>", lambda _event, v=view: self.undo(v))
            ttk.Button(images, text="Open full-size " + ("left", "right")[view],
                       command=lambda v=view: self.native_view(v)).grid(row=1, column=view)
            self.canvases.append(canvas)
        images.rowconfigure(0, weight=1)
        ttk.Label(panel, textvariable=self.pose, font=("monospace", 12), wraplength=920).pack(anchor="w")
        ttk.Label(panel, textvariable=self.status, wraplength=920).pack(anchor="w", pady=6)
        self.timer = parent.after(100, self.tick)

    def invalidate(self):
        if self.busy:
            return
        self.result = None
        self.pose.set("No body pose — label the four physical front corners in each view")
        self.track_button.configure(state="disabled")
        self.replay_button.configure(state="disabled")
        self.redraw()

    def click(self, view, x, y, scale=None):
        if self.busy or self.live or not self.capture or len(self.corners[view]) >= 4:
            return
        scale = self.scales[view] if scale is None else scale
        x, y = x * scale, y * scale
        frame = self.capture["frames"][view]
        if 0 <= x < frame["width"] and 0 <= y < frame["height"]:
            self.corners[view].append([x, y])
            self.invalidate()
            self.status.set(f"Selected {len(self.corners[0])}/4 left, {len(self.corners[1])}/4 right. "
                            "Label the physical top/front, then Estimate pose.")

    def undo(self, view):
        if not self.busy and self.corners[view]:
            self.corners[view].pop()
            self.invalidate()

    def native_view(self, view):
        if not self.images or self.live:
            return
        import tkinter as tk
        from tkinter import ttk
        window = tk.Toplevel(self.parent)
        window.title("Frozen native pixels — " + ("front left", "front right")[view])
        window.geometry("900x700")
        canvas = tk.Canvas(window, background="#151923")
        vertical = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(window, orient="horizontal", command=canvas.xview)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        canvas.pack(fill="both", expand=True)
        canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        # Native selection is bound to the captured pair, never a live preview.
        captured = self.capture
        self.draw(canvas, view, 1)
        canvas.configure(scrollregion=canvas.bbox("all"))
        def select(event):
            if self.capture is captured and not self.live:
                self.click(view, canvas.canvasx(event.x), canvas.canvasy(event.y), 1)
                self.draw(canvas, view, 1)
        canvas.bind("<Button-1>", select)
        def undo(_event):
            if self.capture is captured and not self.live:
                self.undo(view)
                self.draw(canvas, view, 1)
        canvas.bind("<Button-3>", undo)

    def draw(self, canvas, view, scale):
        import tkinter as tk
        canvas.delete("all")
        if not self.images:
            return
        # Tk's PPM handler also reads binary grayscale PGM.
        image = tk.PhotoImage(data=self.images[view], format="PPM")
        canvas.image = image.subsample(scale, scale) if scale > 1 else image
        canvas.create_image(0, 0, image=canvas.image, anchor="nw")
        if self.result:
            for index, candidate in reversed(list(enumerate(self.result.get("candidates", [])[:2]))):
                color = "#52e0a2" if index == 0 and self.result["status"] == "measured" else "#ffbd59"
                for line in candidate["wireframe"][view]:
                    if len(line) > 1:
                        canvas.create_line(*[value / scale for xy in line for value in xy],
                                           fill=color, width=2, dash=() if index == 0 else (4, 4))
        if not self.live:
            for i, (x, y) in enumerate(self.corners[view]):
                x, y = x / scale, y / scale
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#57baff")
                canvas.create_text(x + 9, y - 9, text=str(i + 1), fill="white", anchor="w")

    def redraw(self):
        if not self.images:
            return
        frames = self.result["frames"] if self.live and self.result else self.capture["frames"]
        for view, canvas in enumerate(self.canvases):
            self.scales[view] = max(1, math.ceil(frames[view]["width"] / max(430, canvas.winfo_width())))
            self.draw(canvas, view, self.scales[view])

    def freeze(self):
        if self.busy:
            return
        try:
            link = self.app.phone_panel.link
            snapshot = link.snapshot() if link else None
            session = self.app.sessions / ("body-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
            selections = [value.get() for value in (self.app.left, self.app.right,
                                                   self.app.left_stream, self.app.right_stream)]
            config = create_session(session, snapshot, getattr(self.app.runtime, "factory_root", Path("/")),
                                    selections, self.app.runtime.ring, self.record.get())
            self.session, self.config = session, config
            self.capture = self.result = self.images = self.initial_images = None
            self.corners = [[], []]
            self.labelled.set(False)
            self.pose.set("Waiting for a synchronized capture")
            self.launch("capture", ["--capture"], link=link)
        except (OSError, ValueError, KeyError) as error:
            self.status.set(str(error))

    def solve(self):
        if self.busy or not self.capture:
            return
        if not self.labelled.get() or any(len(points) != 4 for points in self.corners):
            self.status.set("Select all eight corners and confirm the phone's physical top and front.")
            return
        try:
            write_json(self.session / "corners.json", {"schema": "framephone-body-corners-v1",
                       "frames": self.capture["frames"], "physical_top_and_front_labelled": True,
                       "corners": self.corners})
            self.launch("solve", ["--solve"])
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def track(self):
        if self.busy or not self.result or self.result["status"] != "measured":
            return
        link = self.app.phone_panel.link
        snapshot = link.snapshot() if link else None
        if not snapshot or snapshot["session"] != self.config["phone_session"]:
            self.status.set("The phone connection changed. Connect and capture a new pair.")
            return
        self.launch("track", ["--track"], link=link)

    def replay(self):
        if self.busy or not self.result or self.result["status"] != "measured":
            return
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Choose paired-images from this trial", initialdir=self.session)
        if path:
            self.launch("replay", ["--replay", path])

    def open_trial(self):
        if self.busy:
            return
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Choose a markerless session", initialdir=self.app.sessions)
        if not path:
            return
        try:
            session = Path(path)
            config = json.loads((session / "session.json").read_text())
            if config["schema"] != "framephone-markerless-session-v1":
                raise ValueError("Not a markerless session")
            capture = json.loads((session / "capture.json").read_text())
            images = [(session / "initial" / f"pair-1-{v}.pgm").read_bytes() for v in range(2)]
            self.session, self.config, self.capture = session, config, capture
            self.images = self.initial_images = images
            self.corners, self.result, self.live = [[], []], None, False
            self.labelled.set(False)
            if (session / "corners.json").is_file():
                corners = json.loads((session / "corners.json").read_text())
                if corners["frames"] == capture["frames"]:
                    self.corners = corners["corners"]
                    self.labelled.set(corners["physical_top_and_front_labelled"])
            self.solve_button.configure(state="normal")
            self.invalidate()
            self.status.set("Loaded frozen capture. Estimate pose, then Replay images to reproduce a recorded trial.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.set("Cannot open trial: " + str(error))

    def launch(self, mode, args, link=None):
        # A final preview can arrive between the previous tick's preview and
        # completion checks. Never carry it into a different operation.
        try:
            self.latest.get_nowait()
        except queue.Empty:
            pass
        output = self.session / ("run-" + uuid.uuid4().hex[:12]) if mode in ("track", "replay") else None
        recording = None
        try:
            if link and self.config["record"]:
                name = output.name if output else "initial"
                recording = link.start_recording(self.session / (name + "-telemetry.jsonl"))
        except (OSError, ValueError) as error:
            self.status.set("Cannot record telemetry: " + str(error))
            return
        command = self.app.runtime.command("markerless", "--session", self.session, *args)
        if output:
            command += ["--output", str(output)]
        self.busy, self.live = True, output is not None
        if self.live:
            self.result = None
        self.cancelled.clear()
        self.last_update = time.monotonic()
        self.pose.set("Waiting for fresh optical evidence" if output else "Estimating…")
        self.status.set("Hold the phone and headset still for capture / initialization." if mode != "replay" else "Replaying recorded camera frames; IMU is logged only.")
        for button in (self.capture_button, self.solve_button, self.track_button, self.open_button, self.replay_button):
            button.configure(state="disabled")
        for box in self.boxes:
            box.configure(state="disabled")
        def run():
            last, error = None, ""
            code = 1
            try:
                with self.process_lock:
                    if self.cancelled.is_set():
                        return
                    self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                    text=True, bufsize=1)
                    process = self.process
                for line in process.stdout:
                    if line.startswith("{"):
                        last = json.loads(line)
                        if output:
                            images = preview_pair(output, last)
                            if images:
                                try:
                                    self.latest.get_nowait()
                                except queue.Empty:
                                    pass
                                self.latest.put_nowait((last, images))
                    else:
                        error = (error + line)[-4000:]
                code = process.wait()
            except (OSError, ValueError, KeyError) as exc:
                error = str(exc)
            finally:
                with self.process_lock:
                    if self.process and self.process.poll() is None:
                        self.process.kill()
                        self.process.wait()
                    self.process = None
                if recording:
                    link.stop_recording()
                    if recording.error or recording.dropped:
                        error += f"\nTelemetry recording: {recording.error or 'queue overflow'}; dropped {recording.dropped} messages."
                self.events.put((mode, code, last, error))
        threading.Thread(target=run, daemon=True).start()

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
        self.pose.set("Stopped — no live pose")
        self.redraw()

    def show_result(self, result, frozen=False):
        self.result = result
        status = result["status"]
        if status == "measured":
            best = result["candidates"][0]
            x, y, z = best["translation_m"]
            # Intrinsic Z-Y-X Euler angles are display-only; the API retains R_HB.
            r = best["rotation"]
            yaw = math.degrees(math.atan2(r[3], r[0]))
            pitch = math.degrees(math.asin(max(-1., min(1., -r[6]))))
            roll = math.degrees(math.atan2(r[7], r[8]))
            self.pose.set(("Frozen geometry" if frozen else "Optical measurement") +
                f" · XYZ {x:+.3f}, {y:+.3f}, {z:+.3f} m · distance {math.sqrt(x*x+y*y+z*z):.3f} m\n"
                f"Z/Y/X angles {yaw:+.1f}°, {pitch:+.1f}°, {roll:+.1f}° · RMS {best['rms_px']:.2f} px · "
                f"skew {result['capture_skew_ns']/1e6:.2f} ms")
        else:
            self.pose.set(status.capitalize() + " — " + result["reason"].replace("_", " "))
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
        if self.busy and self.live and time.monotonic() - self.last_update > 1:
            self.result = None
            self.pose.set("Stale — no fresh optical measurement")
            self.redraw()
        if self.busy and self.live and self.config and not self.cancelled.is_set():
            # Stop live tracking when its paired phone changes/disconnects.
            with self.process_lock:
                process = self.process
            if process and "--track" in process.args:
                link = self.app.phone_panel.link
                snapshot = link.snapshot() if link else None
                if not snapshot or snapshot["session"] != self.config["phone_session"]:
                    self.stop()
                    self.status.set("Phone disconnected or changed. Capture a new pair after reconnecting.")
        try:
            mode, code, result, error = self.events.get_nowait()
            self.busy = False
            self.live = False
            if self.initial_images:
                self.images = self.initial_images
            for box in self.boxes:
                box.configure(state="readonly")
            self.capture_button.configure(state="normal")
            self.open_button.configure(state="normal")
            if code or self.cancelled.is_set():
                self.result = None
                self.pose.set("Stopped — no live pose")
                self.status.set(error.strip() or "Stopped. Capture a new pair to try again.")
            elif mode == "capture":
                self.capture = result
                self.images = self.initial_images = [(self.session / "initial" / f"pair-1-{v}.pgm").read_bytes() for v in range(2)]
                self.status.set("Captured a synchronized pair. Select four physical front corners in EACH view.")
                self.pose.set("No body pose — waiting for corner selection")
            elif mode == "solve" and result:
                self.live = False
                self.images = self.initial_images
                self.show_result(result, frozen=True)
                if result["status"] == "measured":
                    self.track_button.configure(state="normal")
                    self.replay_button.configure(state="normal")
                self.status.set("Green: best body wireframe; amber: alternatives. Check the front rim in both views. "
                                "Hold the original pose, then Track outline. This is geometry evidence, not verified accuracy.")
            else:
                self.result = None
                self.pose.set("Stopped — no live pose")
                reason = result.get("reason", "end of recording") if result else "end of recording"
                self.status.set("Trial finished: " + reason.replace("_", " ") + ". Capture again to reacquire. " + error.strip())
            if self.capture:
                self.solve_button.configure(state="normal")
            if error and not code:
                self.status.set(self.status.get() + " " + error.strip())
            self.redraw()
        except queue.Empty:
            pass
        except (OSError, ValueError, KeyError) as error:
            self.status.set(str(error))
        if not self.closed:
            self.timer = self.parent.after(100, self.tick)

    def close(self):
        self.closed = True
        self.stop()
        self.parent.after_cancel(self.timer)

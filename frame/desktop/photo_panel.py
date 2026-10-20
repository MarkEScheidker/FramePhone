"""Fixed-photo acquisition and stereo pose. No camera, TLS or UI ownership in workers."""
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

from photo_reference import create_session


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


class PhotoPanel:
    def __init__(self, parent, app):
        import tkinter as tk
        from tkinter import ttk
        self.parent, self.app = parent, app
        self.busy = self.closed = False
        self.process = None
        self.process_lock = threading.Lock()
        self.cancelled = threading.Event()
        self.latest = queue.Queue(maxsize=1)
        self.events = queue.SimpleQueue()
        self.images = self.result = self.config = self.session = None
        self.last_update = 0
        self.reference_id = ""
        self.status = tk.StringVar(value="Choose and show a tracking photo on the phone, then download it here.")
        self.pose = tk.StringVar(value="No current photo pose")
        self.reference_status = tk.StringVar(value="No reference downloaded")
        self.record = tk.BooleanVar(value=False)
        panel = ttk.Frame(parent, padding=12)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Photo stereo tracking", font=("sans", 20, "bold")).pack(anchor="w")
        ttk.Label(panel, text="One photo, sent once from your phone. Stereo estimates its center, angle and distance.",
                  wraplength=900).pack(anchor="w", pady=5)
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=6)
        ttk.Button(actions, text="Use phone photo", command=self.download).pack(side="left")
        ttk.Button(actions, text="Enable cameras", command=app.enable_cameras).pack(side="left", padx=6)
        ttk.Button(actions, text="Refresh cameras", command=app.refresh).pack(side="left")
        ttk.Button(actions, text="Open results", command=lambda: app.open_folder(app.sessions)).pack(side="right")
        self.reference_view = ttk.Label(panel, textvariable=self.reference_status)
        self.reference_view.pack(anchor="w", pady=4)
        self.boxes = []
        mapping = ttk.Frame(panel)
        mapping.pack(fill="x", pady=4)
        for v, (name, factory, stream) in enumerate((("Front left", app.left, app.left_stream),
                                                  ("Front right", app.right, app.right_stream))):
            ttk.Label(mapping, text=name).grid(row=v, column=0, sticky="w")
            for col, variable, collection in ((1, factory, app.factory_boxes), (2, stream, app.stream_boxes)):
                box = ttk.Combobox(mapping, textvariable=variable, state="readonly", width=30)
                box.grid(row=v, column=col, padx=4)
                collection.append(box)
                self.boxes.append(box)
        controls = ttk.Frame(panel)
        controls.pack(fill="x", pady=6)
        self.start_button = ttk.Button(controls, text="Start photo tracking", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(controls, text="Stop", command=self.stop).pack(side="left", padx=8)
        ttk.Checkbutton(controls, text="Record camera trial (512 MiB max)", variable=self.record).pack(side="left")
        images = ttk.Frame(panel)
        images.pack(fill="both", expand=True)
        images.rowconfigure(0, weight=1)
        self.canvases = []
        for v in range(2):
            canvas = tk.Canvas(images, width=430, height=320, background="#151923", highlightthickness=0)
            canvas.grid(row=0, column=v, padx=4, sticky="nsew")
            images.columnconfigure(v, weight=1)
            self.canvases.append(canvas)
        ttk.Label(panel, textvariable=self.pose, font=("monospace", 12), wraplength=920).pack(anchor="w", pady=5)
        ttk.Label(panel, textvariable=self.status, wraplength=920).pack(anchor="w")
        ttk.Label(panel, text="Pose is relative to the headset's factory head frame. ARCore/world alignment is not active.",
                  wraplength=920).pack(anchor="w", pady=3)
        self.timer = parent.after(50, self.tick)

    def download(self):
        if self.busy:
            self.status.set("Stop photo tracking before downloading another reference.")
            return
        try:
            link = self.app.phone_panel.link
            if not link:
                raise ValueError("Connect your phone in Phone telemetry first.")
            link.request_photo()
            self.reference_id = ""
            self.reference_status.set("Downloading photo…")
            self.reference_view.configure(image="")
            self.reference_view.image = None
            self.status.set("Downloading the selected phone photo once…")
        except ValueError as error:
            self.status.set(str(error))

    def start(self):
        if self.busy:
            return
        try:
            link = self.app.phone_panel.link
            snapshot = link.snapshot() if link else None
            if not snapshot:
                raise ValueError("Connect your phone first.")
            data, metadata = link.photo_reference()
            if not metadata:
                raise ValueError("Choose a photo on the phone, then click Use phone photo.")
            state = snapshot["photo"]["state"]
            if state["id"] != metadata["id"] or not state["displayed"]:
                raise ValueError("Show the downloaded photo on the phone before starting.")
            selections = [var.get() for var in (self.app.left, self.app.right, self.app.left_stream, self.app.right_stream)]
            session = self.app.sessions / ("photo-" + uuid.uuid4().hex[:12])
            self.config = create_session(session, getattr(self.app.runtime, "factory_root", Path("/")),
                                         selections, self.app.runtime.ring, data, metadata, snapshot["session"], self.record.get())
            self.session = session
            command = self.app.runtime.command("photo", "--session", session, "--track", "--output", session / "run")
        except (OSError, ValueError, KeyError, ImportError) as error:
            self.status.set(str(error))
            return
        self.cancelled.clear()
        while not self.latest.empty():
            try:
                self.latest.get_nowait()
            except queue.Empty:
                break
        self.images = self.result = None
        self.redraw()
        self.busy = True
        self.last_update = time.monotonic()
        self.pose.set("Acquiring — no current pose")
        self.status.set("Matching photo features in both front cameras…")
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
                        images = preview_pair(session / "run", message)
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
            if self.result and self.result["status"] == "measured":
                for match in self.result["matches"]:
                    x, y = [n/scale for n in match["pixels"][v]]
                    canvas.create_oval(x-2, y-2, x+2, y+2, outline="#52e0a2")
                points = self.result["outline"][v]
                canvas.create_line(*[n/scale for p in points + [points[0]] for n in p], fill="#52e0a2", width=2)

    def show_result(self, result):
        self.result = result
        counts = result["view_inliers"]
        self.status.set(f"Photo inliers: left {counts[0]} · right {counts[1]} · stereo {len(result['matches'])} · "
                        f"{result['processing_ms']:.0f} ms · {result['reason'].replace('_', ' ')}")
        if result["status"] == "measured":
            p = result["pose"]
            x,y,z = p["translation_m"]
            r = p["rotation"]
            angles = (math.degrees(math.atan2(r[3],r[0])), math.degrees(math.asin(max(-1,min(1,-r[6])))),
                      math.degrees(math.atan2(r[7],r[8])))
            self.pose.set(f"Photo XYZ {x:+.3f}, {y:+.3f}, {z:+.3f} m · distance {math.sqrt(x*x+y*y+z*z):.3f} m\n"
                          f"Z/Y/X {angles[0]:+.1f}°, {angles[1]:+.1f}°, {angles[2]:+.1f}° · "
                          f"photo {p['width_m']*1000:.0f}×{p['height_m']*1000:.0f} mm · RMS {p['rms_px']:.2f} px")
        else:
            self.pose.set("Acquiring — no current pose")
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
        self.redraw()

    def tick(self):
        link = self.app.phone_panel.link
        snapshot = link.snapshot() if link else None
        photo = snapshot.get("photo", {}) if snapshot else {}
        meta = photo.get("metadata")
        if meta and meta["id"] != self.reference_id:
            import tkinter as tk
            self.reference_id = meta["id"]
            self.reference_status.set(f"Reference {self.reference_id[:12]} · {meta['width']}×{meta['height']} · downloaded")
            data, _ = link.photo_reference()
            if data:
                try:
                    image = tk.PhotoImage(data=data, format="PNG")
                    image = image.subsample(max(1, math.ceil(max(image.width(), image.height())/150)))
                    self.reference_view.configure(image=image, compound="left")
                    self.reference_view.image = image
                except tk.TclError:
                    self.reference_status.set("Photo thumbnail unavailable; download the reference again.")
            self.status.set("Photo downloaded. Show it on the phone, then Start photo tracking.")
        if photo.get("error"):
            self.status.set(photo["error"])
        if not snapshot and self.reference_id:
            self.reference_id = ""
            self.reference_status.set("Disconnected — download reference after reconnecting")
            self.reference_view.configure(image="")
            self.reference_view.image = None
        try:
            result, images = self.latest.get_nowait()
            if not self.cancelled.is_set():
                self.images = images
                self.last_update = time.monotonic()
                self.show_result(result)
        except queue.Empty:
            pass
        if self.busy and not self.cancelled.is_set():
            state = photo.get("state", {})
            selections = [var.get() for var in (self.app.left, self.app.right, self.app.left_stream, self.app.right_stream)]
            if (not snapshot or snapshot["session"] != self.config["phone_session"] or
                    state.get("id") != self.config["reference_id"] or not state.get("displayed") or
                    selections != [self.config[k] for k in ("left","right","left_stream","right_stream")]):
                self.stop()
                self.status.set("Phone/photo/camera state changed. Show the reference and start again.")
            elif time.monotonic()-self.last_update > 1.5:
                self.result = None
                self.pose.set("Stale — no current pose")
                self.redraw()
        try:
            code, error = self.events.get_nowait()
            self.busy = False
            self.result = None
            self.pose.set("Stopped — no current pose")
            self.start_button.configure(state="normal")
            for box in self.boxes:
                box.configure(state="readonly")
            if error.strip():
                self.status.set(error.strip())
            elif not self.cancelled.is_set():
                self.status.set(f"Tracker finished ({code}). Start again to retry.")
            self.redraw()
        except queue.Empty:
            pass
        if not self.closed:
            self.timer = self.parent.after(50,self.tick)

    def close(self):
        self.closed = True
        self.parent.after_cancel(self.timer)
        self.stop()

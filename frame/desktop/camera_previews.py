"""Bounded native AprilTag previews, independent of phone pairing/stereo solves.

Each child emits one JSON line and an explicitly sized annotated Gray8 PGM.
Pixels are polled independently of the detector, as in the original desktop UI.
Only the newest frame per camera is retained; neither reader runs on Tk's thread.
"""
import json
import queue
import subprocess
import threading
import time

from ring_preview import preview


class CameraPreviews:
    def __init__(self, runtime):
        self.runtime = runtime
        self.workers = {}

    def update(self, view, camera, enabled):
        state = self.workers.get(view)
        if state and (not enabled or state["camera"] != camera):
            self.stop(view)
            state = None
        if not enabled or not camera:
            return
        if state:
            if state["process"] and state["process"].poll() is None:
                return
            if time.monotonic()-state["started"] < 2:
                return
            self.stop(view)
        state = {"camera": camera, "started": time.monotonic(), "process": None,
                 "latest": queue.Queue(maxsize=1), "stopped": threading.Event(),
                 "annotation": None, "annotated_at": 0., "error": "Waiting for tag detector…"}
        self.workers[view] = state

        def deliver(item):
            try:
                state["latest"].get_nowait()
            except queue.Empty:
                pass
            state["latest"].put_nowait(item)

        def pixels():
            # Always read this camera, even when its detector is starting, stuck
            # in detection/stdout, or failing. A healthy detector supplies its own
            # exact annotated image; observations never transfer to raw pixels.
            while not state["stopped"].is_set():
                result, error = None, state["error"]
                try:
                    raw = preview(self.runtime.ring, camera, metadata=True)
                    annotation = state["annotation"]
                    recent = time.monotonic()-state["annotated_at"] < .5
                    if annotation and (recent or (raw and raw[3]["sequence"] == annotation[3]["sequence"])):
                        result = annotation
                    elif raw:
                        width, height, image, metadata = raw
                        result = (width, height, image, dict(metadata, detections=[], frame_status="raw",
                                  reason=error or "Tag annotations unavailable"))
                except (OSError, ValueError) as exc:
                    error = str(exc)
                if not state["stopped"].is_set():
                    deliver((result, "" if result else error))
                state["stopped"].wait(.1)

        threading.Thread(target=pixels, daemon=True).start()
        try:
            process = subprocess.Popen(self.runtime.command("fiducial", "--preview-ring", self.runtime.ring,
                                                            "--camera", camera), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            state["process"] = process
        except OSError as error:
            state["error"] = str(error)
            return

        def read():
            error = "Camera preview process ended"
            last_image = None
            try:
                while not state["stopped"].is_set():
                    line = process.stdout.readline(65537)
                    if not line:
                        break
                    if len(line) > 65536:
                        raise ValueError("Camera preview header exceeds limit")
                    header = json.loads(line)
                    if header.get("schema") != "framephone-camera-preview-v1" or header.get("camera_id") != camera:
                        raise ValueError("Unexpected camera preview identity")
                    size = header["image_bytes"]
                    if type(size) is not int or not 0 <= size <= 16_777_280:
                        raise ValueError("Camera preview size exceeds limit")
                    if size == 0:
                        reason = f"No new readable frames · received {header.get('frames_received', 0)} · sequence {header.get('last_sequence', 0)}"
                        if last_image:
                            width, height, image, previous = last_image
                            paused = dict(previous, frame_status="paused", reason=reason)
                            state["annotation"] = (width, height, image, paused)
                        state["error"] = reason
                        continue
                    width, height = header["width"], header["height"]
                    if any(type(n) is not int or not 1 <= n <= 4096 for n in (width, height)):
                        raise ValueError("Invalid camera preview dimensions")
                    prefix = f"P5\n{width} {height}\n255\n".encode()
                    if size != len(prefix)+width*height:
                        raise ValueError("Invalid camera preview payload size")
                    image = process.stdout.read(size)
                    if len(image) != size or not image.startswith(prefix):
                        raise ValueError("Incomplete camera preview image")
                    last_image = (width, height, image, header)
                    state["annotation"] = last_image
                    state["annotated_at"] = time.monotonic()
                    state["error"] = ""
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=2)
                details = process.stderr.read(4000).decode(errors="replace").strip()
                error = details or f"Camera preview exited ({process.returncode})"
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                error = str(exc)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
                process.stderr.close()
                if not state["stopped"].is_set():
                    state["annotation"] = None
                    state["error"] = error
        threading.Thread(target=read, daemon=True).start()

    def take(self, view):
        state = self.workers.get(view)
        if state:
            try:
                return state["latest"].get_nowait()
            except queue.Empty:
                pass
        return None

    def stop(self, view):
        state = self.workers.pop(view, None)
        if not state:
            return
        state["stopped"].set()
        process = state["process"]
        if process and process.poll() is None:
            process.terminate()
            def reap():
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            threading.Thread(target=reap, daemon=True).start()

    def close(self):
        for view in list(self.workers):
            self.stop(view)

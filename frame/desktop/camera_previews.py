"""Bounded native AprilTag previews, independent of phone pairing/stereo solves.

Each child emits one JSON line and an explicitly sized annotated Gray8 PGM.
Only the newest frame per camera is retained; detection never runs on Tk's thread.
"""
import json
import queue
import subprocess
import threading
import time


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
                 "latest": queue.Queue(maxsize=1), "stopped": threading.Event()}
        self.workers[view] = state

        def deliver(item):
            try:
                state["latest"].get_nowait()
            except queue.Empty:
                pass
            state["latest"].put_nowait(item)

        try:
            process = subprocess.Popen(self.runtime.command("fiducial", "--preview-ring", self.runtime.ring,
                                                            "--camera", camera), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            state["process"] = process
        except OSError as error:
            deliver((None, str(error)))
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
                            deliver(((width, height, image, paused), ""))
                        else:
                            deliver((None, reason))
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
                    deliver((last_image, ""))
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
                    deliver((None, error))
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

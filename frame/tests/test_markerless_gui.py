"""Actual Tk + native capture/solve/tracker against an independent camera ring.

Run under Xvfb with the CMake build directory. No headset/phone/root required.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from app import Runtime, Window

binary = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="framephone-body-gui-") as folder:
    temporary = Path(folder)
    fixture = temporary / "fixture"
    subprocess.run([str(binary / "framephone-markerless-tests"), "--write-trial", str(fixture)], check=True)
    expected = json.loads((fixture / "corners.json").read_text())["corners"]
    images = [(fixture / "initial" / f"pair-1-{v}.pgm").read_bytes().split(b"\n", 3)[3] for v in range(2)]
    width, height = 640, 480
    slot_bytes = 64 + width * height
    data = bytearray(1344 + 8 * slot_bytes)
    struct.pack_into("<8sIIIIQqQ", data, 0, b"FHRING01", 1, 1344, 2, 0, len(data), os.getpid(), time.monotonic_ns())
    for v, name in enumerate((b"slam_left", b"slam_right")):
        offset = 64 + v * 160
        data[offset:offset + 7] = b"og01a1b"
        data[offset + 32:offset + 32 + len(name)] = name
        struct.pack_into("<IIIIIIQQ", data, offset + 64, v, 0, width, height, width, 4,
                         1344 + v * 4 * slot_bytes, slot_bytes)
    ring = temporary / "ring"
    ring.write_bytes(data)
    stop, blank = threading.Event(), threading.Event()
    def publish():
        number = 0
        with ring.open("r+b", buffering=0) as file:
            while not stop.is_set():
                now = time.monotonic_ns()
                number += 1
                os.pwrite(file.fileno(), struct.pack("<Q", now), 40)
                for v in range(2):
                    start = 1344 + (v * 4 + number % 4) * slot_bytes
                    os.pwrite(file.fileno(), struct.pack("<QQQQQIf", 2 * number + 1, number,
                              now + v * 100000, now, now, number, 100.), start)
                    os.pwrite(file.fileno(), bytes([24]) * len(images[v]) if blank.is_set() else images[v], start + 64)
                    os.pwrite(file.fileno(), struct.pack("<Q", 2 * number + 2), start)
                    os.pwrite(file.fileno(), struct.pack("<Q", number), 64 + v * 160 + 104)
                stop.wait(.04)
    class TestRuntime(Runtime):
        def __init__(self):
            self.ring = ring
            self.factory_root = fixture / "factory"
        def command(self, tool, *args):
            return [str(binary / f"framephone-{tool}"), *map(str, args)]
        def calibration_id(self):
            return "synthetic-factory-v1"
        def detector_command(self, *args):
            return [sys.executable, str(Path(__file__).resolve().parents[1] / "desktop/phone_detection.py"),
                    "--model", os.environ["FRAMEPHONE_TEST_DETECTOR_MODEL"], *map(str, args)]
    class Phone:
        def snapshot(self):
            return {"session": "synthetic-phone", "dimensions": (.07, .15, .009)}
        def stop(self):
            pass
    os.environ["XDG_CONFIG_HOME"] = str(temporary / "config")
    os.environ["XDG_STATE_HOME"] = str(temporary / "state")
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *error: errors.append(error)
    window = Window(root, TestRuntime())
    # Keep the real telemetry UI idle; only the snapshot boundary is substituted.
    window.phone_panel.parent.after_cancel(window.phone_panel.timer)
    window.phone_panel.link = Phone()
    window.left.set("slam_left")
    window.right.set("slam_right")
    window.left_stream.set("slam_left")
    window.right_stream.set("slam_right")
    writer = threading.Thread(target=publish)
    writer.start()
    panel = window.markerless_panel
    def until(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            assert not errors, errors
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError((panel.status.get(), panel.pose.get()))
    try:
        window.refresh()
        until(lambda: "scan" not in window.jobs)
        assert set(window.factories) >= {"slam_left", "slam_right"}, window.status.get()
        assert set(window.available_streams) == {"slam_left", "slam_right"}, window.status.get()
        window.self_test()
        until(lambda: window.self_test_result is not None)
        assert window.self_test_result, window.status.get()
        window.show_views.set(True)
        window.toggle_views()
        until(lambda: all(getattr(w, "image", None) for w in window.previews))
        window.open_native_view(0)
        until(lambda: getattr(window.native_views[0][1], "image", None))
        assert window.native_views[0][1].image.width() == width
        assert window.native_views[0][1].image.height() == height
        window.show_views.set(False)
        window.toggle_views()
        assert all(w.image is None for w in window.previews)
        assert "layout" not in json.loads(window.config.read_text())
        if os.environ.get("FRAMEPHONE_TEST_DETECTOR_MODEL"):
            original_images = images[:]
            if os.environ.get("FRAMEPHONE_TEST_DETECTOR_PHOTO"):
                import cv2 as cv
                photo = cv.imread(os.environ["FRAMEPHONE_TEST_DETECTOR_PHOTO"], cv.IMREAD_GRAYSCALE)
                photo = cv.resize(photo, (width, height)).tobytes()
                images[:] = [photo, photo]
                time.sleep(.1)
            panel.detect()
            until(lambda: panel.result is not None and "detections" in panel.result, timeout=30)
            assert panel.live and panel.capture is None
            assert "Phones detected:" in panel.pose.get()
            assert not panel.corners[0] and not panel.corners[1]
            if os.environ.get("FRAMEPHONE_TEST_DETECTOR_PHOTO"):
                assert all(panel.result["detections"]), panel.result
                assert any(panel.canvases[0].type(item) == "rectangle" for item in panel.canvases[0].find_all())
                blank.set()
                until(lambda: panel.result is not None and not any(panel.result["detections"]), timeout=15)
                assert not any(panel.canvases[0].type(item) == "rectangle" for item in panel.canvases[0].find_all())
                blank.clear()
            panel.stop()
            until(lambda: not panel.busy)
            assert panel.result is None
            images[:] = original_images
            time.sleep(.1)
        panel.freeze()
        until(lambda: not panel.busy and panel.capture is not None)
        for view in range(2):
            for x, y in expected[view]:
                panel.click(view, x, y, 1)
        panel.labelled.set(True)
        # A rejected fit must leave an actionable reason rather than generic success advice.
        bad = [points.copy() for points in panel.corners]
        panel.corners[1][2] = [bad[1][2][0], bad[1][2][1] + 40]
        panel.solve()
        until(lambda: not panel.busy)
        assert panel.result["status"] != "measured"
        assert "Cannot start tracking:" in panel.status.get()
        assert str(panel.track_button["state"]) == "disabled"
        panel.corners = bad
        panel.solve()
        until(lambda: not panel.busy)
        assert panel.result["status"] == "measured", panel.status.get()
        assert "Frozen geometry" in panel.pose.get()
        assert panel.canvases[0].find_all()
        panel.track()
        until(lambda: panel.busy and panel.result is not None and "Optical measurement" in panel.pose.get())
        blank.set()
        until(lambda: not panel.busy)
        assert panel.result is None and "no live pose" in panel.pose.get()
        assert "outline missing" in panel.status.get(), panel.status.get()
        logs = list(panel.session.glob("run-*/poses.jsonl"))
        assert logs and json.loads(logs[0].read_text().splitlines()[-1])["status"] == "lost"
        assert not list(panel.session.glob("*telemetry*")), "recording must be opt-in"
        print("Camera discovery, previews, self-test, markerless capture/solve/track and loss clearing passed")
    finally:
        stop.set()
        writer.join(timeout=2)
        panel.close()
        window.phone_panel.close()
        root.destroy()

"""Real Tk window + native live detection, using an independent camera-ring writer.

Run under xvfb-run with the native build directory as the argument. No headset,
root, factory calibration, phone layout or camera broker is used.
"""
import os
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
from app import Runtime, Window

binary_dir = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="framephone-front-gui-") as directory:
    temp = Path(directory)
    os.environ["XDG_CONFIG_HOME"] = str(temp / "config")
    os.environ["XDG_STATE_HOME"] = str(temp / "state")
    subprocess.run([str(binary_dir / "framephone-frame"), "--synthetic", "1", str(temp / "images")],
                   check=True, capture_output=True)
    image = (temp / "images/frame-0.pgm").read_bytes().split(b"\n", 3)[3]
    assert len(image) == 640 * 480
    # Independent 2x raster plus padding exercises real 1280x1024 input. The
    # previous sensor filter hid these candidates in favor of the other pair.
    rows = [bytes(value for value in image[y * 640:(y + 1) * 640] for _ in range(2))
            for y in range(480)]
    image = bytes([24]) * (1280 * 32) + b"".join(row * 2 for row in rows) + bytes([24]) * (1280 * 32)
    streams = ["candidate_video0", "candidate_video3"]
    slot_bytes = 64 + len(image)
    offsets = [1344, 1344 + 4 * slot_bytes]
    side_slot_bytes = 64 + 640 * 640
    data = bytearray(1344 + 8 * slot_bytes + 2 * side_slot_bytes)
    struct.pack_into("<8sIIIIQQQ", data, 0, b"FHRING01", 1, 1344, 4, 0,
                     len(data), os.getpid(), time.monotonic_ns())
    for index, stream in enumerate(streams):
        offset = 64 + index * 160
        data[offset:offset + 7] = b"og01a1b"
        data[offset + 32:offset + 32 + len(stream)] = stream.encode()
        struct.pack_into("<IIIIIIQQ", data, offset + 64, (0, 3)[index], 0, 1280, 1024, 1280, 4,
                         offsets[index], slot_bytes)
    for index, node in enumerate((13, 9), 2):
        offset = 64 + index * 160
        data[offset:offset + 7] = b"og0ve10"
        name = f"candidate_video{node}".encode()
        data[offset + 32:offset + 32 + len(name)] = name
        struct.pack_into("<IIIIIIQQ", data, offset + 64, node, 0, 640, 640, 640, 1,
                         1344 + 8 * slot_bytes + (index - 2) * side_slot_bytes, side_slot_bytes)
    ring = temp / "ring"
    ring.write_bytes(data)
    done, blank, paused = threading.Event(), threading.Event(), threading.Event()

    def publish():
        with ring.open("r+b", buffering=0) as output:
            fd, number = output.fileno(), 0
            while not done.is_set():
                now = time.monotonic_ns()
                os.pwrite(fd, struct.pack("<Q", now), 40)
                if not paused.is_set():
                    number += 1
                    for index in range(2):
                        offset = offsets[index] + (number % 4) * slot_bytes
                        os.pwrite(fd, struct.pack("<QQQQQIf", 2 * number + 1, number,
                                                 now, now, now, number, 100.0), offset)
                        os.pwrite(fd, bytes([24]) * len(image) if blank.is_set() else image, offset + 64)
                        os.pwrite(fd, struct.pack("<Q", 2 * number + 2), offset)
                        os.pwrite(fd, struct.pack("<Q", number), 64 + index * 160 + 104)
                done.wait(.05)

    class TestRuntime(Runtime):
        def __init__(self):
            self.ring = ring
        def command(self, tool, *args):
            return [str(binary_dir / f"framephone-{tool}"), *map(str, args)]

    root = tk.Tk()
    failures = []
    root.report_callback_exception = lambda *error: failures.append(error)
    settings = temp / "config/framephone/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"left": "upper_left", "right": "upper_right",
                                   "left_stream": "candidate_video13", "right_stream": "candidate_video9"}))
    window = Window(root, TestRuntime())
    assert not any(value.get() for value in (window.left, window.right, window.left_stream, window.right_stream))
    writer = threading.Thread(target=publish)
    writer.start()

    def until(predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            root.update()
            assert not failures, failures
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError((window.markers.get(), window.marker_details.cget("text"),
                              (temp / "state/framephone/desktop.log").read_text()))

    try:
        discovery = ("candidate_video0 sensor=og01a1b 3-0036 video0 1280x1024 flags=0\n"
                     "candidate_video3 sensor=og01a1b 3-0060 video3 1280x1024 flags=0\n"
                     "candidate_video13 sensor=og0ve10 4-0036 video13 640x640 flags=0\n"
                     "candidate_video9 sensor=og0ve10 4-0060 video9 640x640 flags=0\n")
        factories = ("upper_left  640x640 KB4 origin_H_m=0 0 0\nupper_right  640x640 KB4 origin_H_m=0 0 0\n"
                     "slam_left  1280x1024 KB4 origin_H_m=0 0 0\nslam_right  1280x1024 KB4 origin_H_m=0 0 0\n")
        window.events.put(("scan", factories, discovery))
        until(lambda: len(window.available_streams) == 4)
        assert len(window.factory_boxes[0].cget("values")) == 4
        window.left_stream.set(streams[0])
        window.right_stream.set(streams[1])
        window.spawn("camera", ["sleep", "30"])
        until(lambda: "4 tracking marker IDs" in window.markers.get())
        assert not window.layout.get()  # Detection requires neither layout nor pose calibration.
        assert "1280×1024 input" in window.marker_details.cget("text")
        assert "video0 • og01a1b" in window.marker_details.cget("text")
        assert sorted(window.worker_streams.values()) == streams
        window.left.set("upper_left")
        window.right.set("upper_right")
        window.start()
        assert "calibrated at 640×640" in window.status.get()
        assert "tracker" not in window.processes and not window.sessions.exists()
        window.show_views.set(True)
        window.toggle_views()
        window.open_native_view(0)
        until(lambda: getattr(window.native_views[0][1], "image", None) is not None)
        assert window.native_views[0][1].image.width() == 1280
        assert window.previews[0].image.width() == 320
        window.show_views.set(False)
        window.toggle_views()
        assert not window.preview_panel.winfo_ismapped()
        blank.set()
        until(lambda: window.markers.get() == "0 tracking markers detected")
        blank.clear()
        until(lambda: "4 tracking marker IDs" in window.markers.get())
        paused.set()
        until(lambda: "Waiting" in window.markers.get())
        paused.clear()
        until(lambda: "4 tracking marker IDs" in window.markers.get())
    finally:
        window.close()
        root.mainloop()
        done.set()
        writer.join()
        for process in window.processes.values():
            process.wait(timeout=3)
        window.logfile.close()
        window.lock.close()
    assert not failures, failures
print("Front-camera GUI: all mono candidates, old mapping reset, 1280x1024 native decoding, calibration mismatch, selected-pair counts, loss/stale/reacquisition and view controls passed.")

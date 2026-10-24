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
    subprocess.run([str(binary / "framephone-fiducial-tests"), "--write-trial", str(fixture)], check=True)
    images = [(fixture / "motion" / f"pair-1-{v}.pgm").read_bytes().split(b"\n", 3)[3] for v in range(2)]
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
    stop, blank, pause = threading.Event(), threading.Event(), threading.Event()
    def publish():
        number = 0
        with ring.open("r+b", buffering=0) as file:
            while not stop.is_set():
                if pause.is_set():
                    stop.wait(.02)
                    continue
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
        overlay_command = None
        def __init__(self):
            self.ring = ring
            self.factory_root = fixture / "factory"
        def command(self, tool, *args):
            if tool == "overlay" and self.overlay_command:
                return [*self.overlay_command, *map(str, args)]
            return [str(binary / f"framephone-{tool}"), *map(str, args)]
        def calibration_id(self):
            return "synthetic-factory-v1"
    target = {"family": "tag36h11", "id": 0, "black_edge_m": .06,
              "origin": "black_square_center", "axes": "right_up_front", "size_source": "manual_black_edge"}
    class Phone:
        displayed = True
        def snapshot(self):
            return {"session": "synthetic-phone", "dimensions": (.07, .15, .009), "fiducial": target,
                    "marker_displayed": self.displayed, "marker_state_fresh": True}
        def stop(self):
            pass
    os.environ["XDG_CONFIG_HOME"] = str(temporary / "config")
    os.environ["XDG_STATE_HOME"] = str(temporary / "state")
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *error: errors.append(error)
    runtime = TestRuntime()
    window = Window(root, runtime)
    # Keep the real telemetry UI idle; only the snapshot boundary is substituted.
    window.phone_panel.parent.after_cancel(window.phone_panel.timer)
    phone = Phone()
    window.phone_panel.link = phone
    window.left.set("slam_left")
    window.right.set("slam_right")
    window.left_stream.set("slam_left")
    window.right_stream.set("slam_right")
    writer = threading.Thread(target=publish)
    writer.start()
    panel = window.tracking_panel
    # Observe the actual process/atomic-pose handoff without requiring a GPU or
    # SteamVR. Native geometry/loader failures are checked separately by CTest.
    helper = temporary / "observe_overlay.py"
    observed = temporary / "overlay-states"
    helper.write_text("import json,sys,time\nfrom pathlib import Path\n"
                      "session=Path(sys.argv[-1])\n"
                      f"log=Path({str(observed)!r}).open('a',buffering=1)\n"
                      "print('VR screen ready: synthetic process observer',flush=True)\n"
                      "previous=None\nwhile True:\n"
                      "    state=json.loads((session/'vr-pose.json').read_text())['status']\n"
                      "    if state!=previous: log.write(state+'\\n'); previous=state\n"
                      "    time.sleep(.01)\n")
    runtime.overlay_command = [sys.executable, "-B", str(helper)]
    panel.vr_enabled.set(True)
    def until(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            assert not errors, errors
            if predicate(): return
            time.sleep(.01)
        raise AssertionError((panel.status.get(), panel.pose.get()))
    try:
        window.refresh()
        until(lambda: "scan" not in window.jobs)
        assert set(window.available_streams) == {"slam_left", "slam_right"}
        window.self_test()
        until(lambda: window.self_test_result is not None)
        assert window.self_test_result
        window.show_views.set(True)
        window.toggle_views()
        until(lambda: all(getattr(w, "image", None) for w in window.previews))
        panel.start()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        assert "Marker center XYZ" in panel.pose.get()
        assert "left 1" in panel.status.get() and "right 1" in panel.status.get()
        until(lambda: observed.exists() and "measured" in observed.read_text())
        assert "processed_host_monotonic_ns" in json.loads((panel.session/"vr-pose.json").read_text())
        pause.set()
        until(lambda: panel.result is None and "Stale" in panel.pose.get())
        assert json.loads((panel.session/"vr-pose.json").read_text())["status"] == "lost"
        pause.clear()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        blank.set()
        until(lambda: panel.result is not None and panel.result["status"] == "lost")
        assert "no current pose" in panel.pose.get()
        assert not panel.result["candidates"]
        until(lambda: "lost" in observed.read_text())
        blank.clear()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        assert not list(panel.session.glob("*telemetry*")), "recording must be opt-in"
        assert not (panel.session/"corners.json").exists()
        phone.displayed = False
        until(lambda: not panel.busy and "overlay" not in window.processes)
        assert json.loads((panel.session/"vr-pose.json").read_text())["status"] == "lost"
        assert "marker hidden" in panel.status.get()
        phone.displayed = True
        panel.start()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        window.phone_panel.link = None
        until(lambda: not panel.busy and "overlay" not in window.processes)
        assert panel.result is None and "no current pose" in panel.pose.get()
        assert "disconnected" in panel.status.get().lower(), panel.status.get()
        assert (panel.session/"tracker.log").exists()
        print("Tk single-tag pose, VR process/publication, stale/blank loss, marker hiding, reacquisition and disconnect clearing passed")
    finally:
        stop.set()
        writer.join(timeout=2)
        panel.close()
        window.phone_panel.close()
        for name in list(window.processes):
            window.terminate(name)
        root.destroy()

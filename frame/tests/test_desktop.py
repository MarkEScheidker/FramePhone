"""Check GUI handoff and bounded previews without root, cameras or a display."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
import front_cameras as front


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "desktop" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app, reader = load("app"), load("ring_preview")


class DesktopTests(unittest.TestCase):
    def test_tracking_handoff_and_fresh_results(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "FRAMEPHONE_RUNTIME_ROOT": folder, "FRAMEPHONE_LOADER": "/bundled/loader",
                "FRAMEPHONE_LIBRARY_PATH": "/bundled/lib"}):
            runtime = app.Runtime()
            runtime.calibration_id = lambda: "test-factory"
            layout = Path(folder) / "layout $(touch SHOULD_NOT_EXIST).json"
            layout.write_text('{"test": true}')
            session = Path(folder) / "test results"
            args = runtime.tracking_command(str(layout), "upper_left", "upper_right", "stream0", "stream1", session, True)
            self.assertEqual(args[:3], ["/bundled/loader", "--library-path", "/bundled/lib"])
            self.assertEqual(args[args.index("--phone-layout") + 1], str(session / "layout.json"))
            self.assertEqual((session / "layout.json").read_bytes(), layout.read_bytes())
            self.assertIn("--record-dir", args)
            self.assertFalse((Path(folder) / "SHOULD_NOT_EXIST").exists())
            with self.assertRaises(FileExistsError):
                runtime.tracking_command(str(layout), "upper_left", "upper_right", "stream0", "stream1", session, False)
            with self.assertRaises(ValueError):
                runtime.tracking_command(str(layout), "upper_left", "upper_right", "same", "same", Path(folder) / "bad", False)
            self.assertFalse((Path(folder) / "bad").exists())
            # Neither family of factory names proves physical front/side identity.
            runtime.tracking_command(str(layout), "slam_left", "slam_right", "stream0", "stream1", Path(folder) / "other-pair", False)
            command = runtime.detection_command("front0")
            self.assertIn("--live-status", command)
            self.assertNotIn("--phone-layout", command)
            with patch.object(app.shutil, "which", return_value="/usr/bin/pkexec"):
                command = runtime.camera_command()
            self.assertNotIn("--sensor", command)  # Must not hide the owner's front pair.

    def test_front_selection_and_detector_feedback(self):
        cameras = ("candidate_video0 sensor=og01a1b 3-0036 video0 1280x1024 flags=0\n"
                   "candidate_video3 sensor=og01a1b 3-0060 video3 1056x1024 flags=0\n"
                   "candidate_video13 sensor=og0ve10 4-0060 video13 640x640 flags=0\n"
                   "candidate_video9 sensor=og0ve10 4-0036 video9 640x640 flags=0\n"
                   "front_dark sensor=og0ve10 4-0036 video7 640x480 flags=1\n"
                   "color sensor=imx616 video8 2464x2464 flags=2\n")
        found = front.mono_streams(cameras)
        self.assertEqual(list(found), ["candidate_video0", "candidate_video3", "candidate_video13", "candidate_video9"])
        self.assertEqual((found["candidate_video0"]["width"], found["candidate_video0"]["height"]), (1280, 1024))
        self.assertEqual(found["candidate_video13"]["height"], 640)  # Preserve reported dimensions.
        self.assertEqual(front.factory_cameras("slam_left  1280x1024 KB4 origin_H_m=0 0 0\nupper_left  640x640 KB4 origin_H_m=0 0 0\n"),
                         {"slam_left": {"width": 1280, "height": 1024}, "upper_left": {"width": 640, "height": 640}})
        line = "detection frame=42 evaluated=1 tags=3 ids=0,2,5 width=640 height=480 processing_ms=3.5"
        progress = front.parse_progress(line)
        self.assertEqual(front.marker_text(progress["views"][0]), "3 markers — IDs 0, 2, 5")
        self.assertIsNone(front.parse_progress(line.replace("tags=3", "tags=4")))
        self.assertIsNone(front.parse_progress(line.replace("ids=0,2,5", "ids=0,2,99")))
        self.assertIsNone(front.parse_progress(line.replace("width=640", "width=0")))
        self.assertIsNone(front.parse_progress("Processed 3 synthetic frames"))
        pair = front.parse_progress("pair=1 tags=3/2 shared=2 skew_us=100 status=ambiguous left_ids=0,2,5 left_size=640x480 right_ids=0,2 right_size=640x480 processing_ms=5")
        self.assertEqual([v["count"] for v in pair["views"]], [3, 2])
        self.assertIn("ambiguous", front.pose_text(pair))
        self.assertNotIn("Phone tracked", front.pose_text(pair))

    def test_live_markers_clear_on_loss_and_stale_input(self):
        class Display:
            def __init__(self, value=""):
                self.value, self.options = value, {}
            def get(self):
                return self.value
            def set(self, value):
                self.value = value
            def configure(self, **options):
                self.options.update(options)
        window = app.Window.__new__(app.Window)
        window.processes = {"detect-left": object(), "detect-right": object()}
        window.worker_streams = {"detect-left": "left", "detect-right": "right"}
        window.stream_info = {}
        window.left_stream, window.right_stream = Display("left"), Display("right")
        window.markers, window.pose = Display(), Display()
        window.marker_label, window.marker_details = Display(), Display()
        window.telemetry_lock = threading.Lock()
        detected = front.parse_progress("detection frame=1 evaluated=1 tags=2 ids=0,2 width=640 height=480")
        window.telemetry = {name: (time.monotonic(), detected) for name in window.processes}
        window.update_markers()
        self.assertIn("2 tracking marker IDs", window.markers.value)  # Stereo views don't double count.
        blank = front.parse_progress("detection frame=2 evaluated=1 tags=0 ids=- width=640 height=480")
        window.telemetry = {name: (time.monotonic(), blank) for name in window.processes}
        window.update_markers()
        self.assertEqual(window.markers.value, "0 tracking markers detected")
        window.telemetry = {name: (time.monotonic() - 2, detected) for name in window.processes}
        window.update_markers()
        self.assertIn("Waiting", window.markers.value)
        self.assertNotIn("2 markers", window.marker_details.options["text"])
        accepted = front.parse_progress("pair=1 tags=2/2 shared=2 skew_us=0 status=accepted left_ids=0,2 left_size=640x480 right_ids=0,2 right_size=640x480 distance_m=0.35 processing_ms=5")
        window.processes = {"tracker": object()}
        window.telemetry = {"tracker": (time.monotonic(), accepted)}
        window.update_markers()
        self.assertIn("Phone tracked", window.pose.value)
        window.telemetry["tracker"] = (time.monotonic() - 2, accepted)
        window.update_markers()
        self.assertEqual(window.pose.value, "No live phone pose")

    def test_host_tools_do_not_inherit_bundled_libraries(self):
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundled", "LD_PRELOAD": "bad.so", "PYTHONHOME": "/bundled", "TK_LIBRARY": "/bundled", "DISPLAY": ":99", "FRAMEPHONE_LOADER": "/bundled"}):
            env = app.host_environment()
            self.assertEqual(env["DISPLAY"], ":99")
            self.assertFalse(any(k.startswith(("LD_", "PYTHON", "TK_", "FRAMEPHONE_")) for k in env))

    def test_preview_sequence_bounds_and_writer_lifetime(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ring"
            data = bytearray(1344 + 128)
            struct.pack_into("<8sIIIIQqQ", data, 0, b"FHRING01", 1, 1344, 1, 0, len(data), 123, time.monotonic_ns())
            data[96:100] = b"test"
            struct.pack_into("<iIIIIIQQQ", data, 128, 0, 0, 2, 2, 2, 1, 1344, 128, 1)
            struct.pack_into("<QQ", data, 1344, 4, 1)
            data[1408:1412] = bytes([0, 70, 150, 255])
            path.write_bytes(data)
            width, height, pgm = reader.preview(path, "test")
            self.assertEqual((width, height), (2, 2))
            self.assertTrue(pgm.endswith(bytes([0, 70, 150, 255])))
            self.assertIsNone(reader.preview(path, "other"))
            struct.pack_into("<Q", data, 1344, 3)  # In-progress write must not be displayed.
            path.write_bytes(data)
            self.assertIsNone(reader.preview(path, "test"))
            struct.pack_into("<Q", data, 152, 10**12)  # Out-of-file slot.
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                reader.preview(path, "test")
            struct.pack_into("<Q", data, 40, 0)  # Broker cleanly stopped.
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                reader.preview(path, "test")
            path.write_bytes(b"truncated")
            with self.assertRaises(ValueError):
                reader.preview(path, "test")


if __name__ == "__main__":
    unittest.main()

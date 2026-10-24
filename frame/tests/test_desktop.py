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

    def test_requested_defaults_preserve_explicit_selection(self):
        left, right = front.DEFAULT_CAMERAS
        self.assertEqual(left, ("slam_left", "og01a1b_4-0060_video3"))
        self.assertEqual(right, ("slam_right", "og01a1b_4-0036_video0"))
        available = [left[1], right[1], "custom"]
        self.assertEqual(front.default_selection("", available, left[1]), left[1])
        self.assertEqual(front.default_selection("custom", available, left[1]), "custom")
        self.assertEqual(front.default_selection("old", ["unrelated_video3"], left[1]), "")





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
            self.assertEqual(reader.preview(path, "test", metadata=True)[3],
                             {"camera_id": "test", "sequence": 1, "capture_timestamp_ns": 0,
                              "publish_monotonic_ns": 0,
                              "clock": "steam-frame-mono-v4l2"})
            self.assertIsNone(reader.preview(path, "other"))
            struct.pack_into("<Q", data, 1344, 3)  # In-progress write must not be displayed.
            path.write_bytes(data)
            self.assertIsNone(reader.preview(path, "test"))
            struct.pack_into("<Q", data, 152, 10**12)  # Out-of-file slot.
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                reader.preview(path, "test")

    def test_preview_accepts_padded_rows_without_displaying_padding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"ring"
            data = bytearray(1344+128)
            now = time.monotonic_ns()
            struct.pack_into("<8sIIIIQqQ",data,0,b"FHRING01",1,1344,1,0,len(data),123,now)
            data[96:100] = b"test"
            struct.pack_into("<iIIIIIQQQ",data,128,0,0,2,2,4,1,1344,128,1)
            struct.pack_into("<QQQQQ",data,1344,4,1,456,now,now)
            data[1408:1416] = bytes([0,70,222,222,150,255,222,222])
            path.write_bytes(data)
            width,height,pgm,metadata = reader.preview(path,"test",metadata=True)
            self.assertEqual((width,height),(2,2))
            self.assertEqual(pgm,b"P5\n2 2\n255\n"+bytes([0,70,150,255]))
            self.assertEqual(metadata["publish_monotonic_ns"],now)
            struct.pack_into("<QQ", data, 64+112, 7, 3)
            path.write_bytes(data)
            status = reader.diagnostics(path, "test")
            self.assertEqual((status["latest_sequence"],status["published_frames"],status["dropped_frames"]),(1,7,3))
            with self.assertRaises(ValueError):
                reader.diagnostics(path, "absent")
            struct.pack_into("<Q", data, 40, 0)  # Broker cleanly stopped.
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                reader.preview(path, "test")
            path.write_bytes(b"truncated")
            with self.assertRaises(ValueError):
                reader.preview(path, "test")


if __name__ == "__main__":
    unittest.main()

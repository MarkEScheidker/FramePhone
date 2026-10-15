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

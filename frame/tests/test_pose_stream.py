"""Renderer poses advance without Tk callbacks; only the newest validated state is published."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from pose_stream import PoseStream


class PoseStreamTests(unittest.TestCase):
    def until(self, predicate):
        deadline = time.monotonic()+2
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("renderer publication did not advance")
            time.sleep(.005)

    def test_latest_delivery_and_shutdown_without_ui_timer(self):
        latest = {"schema": "framephone-arcore-v1", "clock_valid": True,
                  "received_host_monotonic_ns": 123, "poses": [{"seq": 1}]}
        lock = threading.Lock()
        def source():
            with lock:
                return copy.deepcopy(latest)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"phone-pose.json"
            stream = PoseStream(path, source, "phone-1")
            try:
                self.until(path.exists)
                before = path.stat().st_mtime_ns
                time.sleep(.04)
                self.assertEqual(path.stat().st_mtime_ns, before, "unchanged data must not get a fresh timestamp")
                with lock:
                    for i in range(2, 101):
                        latest["poses"][0]["seq"] = i
                self.until(lambda: json.loads(path.read_text())["poses"][-1]["seq"] == 100)
                self.assertEqual(json.loads(path.read_text())["received_host_monotonic_ns"], 123)
                self.assertIsNone(stream.error)
            finally:
                stream.close()
            self.assertFalse(stream.thread.is_alive())
            self.assertFalse(json.loads(path.read_text())["clock_valid"])
            self.assertEqual(json.loads(path.read_text())["poses"], [])

    def test_bad_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"phone-pose.json"
            stream = PoseStream(path, lambda: {"invalid": float("nan")}, "phone-1")
            try:
                self.until(lambda: stream.error is not None)
            finally:
                stream.close()
            self.assertFalse(json.loads(path.read_text())["clock_valid"])


if __name__ == "__main__":
    unittest.main()

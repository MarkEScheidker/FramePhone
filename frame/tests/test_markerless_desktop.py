"""Session provenance and opt-in sensor recording without a GUI or headset."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
from markerless_panel import create_session, preview_pair
from telemetry_recording import TelemetryRecording, evidence_message
from phone_link import PhoneLink, Telemetry
from test_phone_link import profile, batch


class MarkerlessDesktopTests(unittest.TestCase):
    def test_session_freezes_dimensions_and_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "session"
            snapshot = {"dimensions": (.07, .15, .009), "session": "authenticated-test"}
            root = ROOT / "tests/fixtures/stereo-factory"
            config = create_session(target, snapshot, root,
                ["slam_left", "slam_right", "front0", "front1"], Path("/run/test/ring"), False)
            self.assertEqual(config["body_axes"], "centered_right_top_front")
            self.assertEqual(config["phone_body"]["thickness_m"], .009)
            self.assertFalse(config["record"])
            self.assertEqual((target / "factory/persist/xrservice.json").read_bytes(),
                             (root / "persist/xrservice.json").read_bytes())
            with self.assertRaises(FileExistsError):
                create_session(target, snapshot, root, ["a", "b", "c", "d"], Path("ring"), False)

    def test_preview_cannot_use_another_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            slot = root / "preview-1"
            slot.mkdir()
            (slot / "token.json").write_text("4")
            for v in range(2):
                (slot / f"{v}.pgm").write_bytes(b"PGM")
            self.assertIsNone(preview_pair(root, {"preview_slot": 1, "pair": 1}))
            self.assertEqual(preview_pair(root, {"preview_slot": 1, "pair": 4}), [b"PGM", b"PGM"])
            (slot / "token.json").unlink()
            self.assertIsNone(preview_pair(root, {"preview_slot": 1, "pair": 4}))

    def test_record_exact_times_and_report_drops(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sensors.jsonl"
            recording = TelemetryRecording(path, profile(), 10_000_000_001)
            sample = batch(1, 9_000_000_123)
            recording.submit(sample, 10_000_000_456)
            recording.close()
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records[1]["message"], sample)
            self.assertEqual(records[1]["received_host_monotonic_ns"], 10_000_000_456)
            self.assertTrue(records[-1]["end"])
            self.assertEqual(records[-1]["recorder_dropped_messages"], 0)
            with self.assertRaises(FileExistsError):
                TelemetryRecording(path, profile(), 1)

    def test_record_requires_active_authenticated_profile(self):
        link = PhoneLink(None, lambda *_: None, None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "samples.jsonl"
            with self.assertRaises(ValueError):
                link.start_recording(path)
            self.assertFalse(path.exists())
            link.profile, link.telemetry = profile(), Telemetry(profile())
            link.profile_received_ns = time.monotonic_ns()
            recording = link.start_recording(path)
            with self.assertRaises(ValueError):
                link.start_recording(Path(folder) / "another.jsonl")
            link.stop_recording()
            self.assertFalse(recording.thread.is_alive())

    def test_logs_exclude_unknown_fields_and_credentials(self):
        data = profile()
        data["credential"] = "not-sensor-evidence"
        data["sensors"][0]["credential"] = "not-sensor-evidence"
        self.assertNotIn("credential", json.dumps(evidence_message(data)))
        with self.assertRaises(ValueError):
            evidence_message({"type": "paired", "credential": "never-log"})


if __name__ == "__main__":
    unittest.main()

"""ARCore extension validation, bounded history and cross-clock pose export."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from phone_link import PhoneLink, Telemetry
from telemetry_recording import evidence_message
from test_phone_link import profile


def pose_message(seq=1, stamp=1_000_000_000):
    return {"type": "arcore_pose", "session": "test-session", "generation": "anchor-1",
            "acquisition": "scan-1", "seq": seq, "t_ns": stamp, "frame_timestamp_ns": stamp-10,
            "transform": "T_AD", "time_source": "update_elapsed_realtime_ns", "state": "tracking",
            "marker_required": True, "translation_m": [0, .2, -.5], "quaternion_xyzw": [0, 0, 0, 1]}


class ArcoreLinkTests(unittest.TestCase):
    def telemetry(self):
        return Telemetry(dict(profile(), arcore_pose_v1=True))

    def test_clock_mapping_history_limit_reset_and_loss(self):
        state = self.telemetry()
        state.clock_reply({"session": "test-session", "h0": 1_900_000_000,
                           "p1": 900_500_000, "p2": 900_500_000}, 1_901_000_000, {1_900_000_000})
        for i in range(100):
            state.receive(pose_message(i+1, 1_000_000_000+i*10_000_000), 2_000_000_000+i*10_000_000)
        result = state.snapshot(3_000_000_000)["arcore"]
        self.assertTrue(result["clock_valid"])
        self.assertEqual(len(result["poses"]), 90)
        self.assertEqual(result["poses"][-1]["host_t_ns"], 2_990_000_000)
        changed = dict(pose_message(), generation="anchor-2", state="paused")
        state.receive(changed, 3_010_000_000)
        self.assertEqual(len(state.arcore_poses), 1)
        self.assertNotIn("translation_m", state.arcore_poses[-1])
        self.assertFalse(state.snapshot(15_000_000_000)["arcore"]["clock_valid"])

    def test_malformed_unannounced_reordered_poses_rejected(self):
        with self.assertRaises(ValueError):
            Telemetry(profile()).receive(pose_message(), 2_000_000_000)
        for fields in ({"quaternion_xyzw": [0, 0, 0, 0]}, {"quaternion_xyzw": [0, 0, 0, float("nan")]},
                       {"translation_m": [0, False, 0]}, {"seq": 0}, {"t_ns": 1.2},
                       {"generation": "x"*65}, {"marker_required": 1}, {"session": "old"},
                       {"transform": "T_WM"}, {"state": "unknown"}, {"time_source": "camera_exposure"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.telemetry().receive(dict(pose_message(), **fields), 2_000_000_000)
        state = self.telemetry()
        state.receive(pose_message(), 2_000_000_000)
        with self.assertRaises(ValueError):
            state.receive(pose_message(), 2_000_000_001)

    def test_snapshot_and_recording_do_not_leak_unknown_fields(self):
        state = self.telemetry()
        sample = dict(pose_message(), credential="never-export")
        state.receive(sample, 2_000_000_000)
        sample["translation_m"][0] = 123
        self.assertEqual(state.arcore_poses[-1]["translation_m"][0], 0)
        self.assertNotIn("credential", json.dumps(evidence_message(sample)))

    def test_alignment_commands_are_bounded_and_session_bound(self):
        link = PhoneLink(None, None, None)
        self.assertFalse(link.alignment_command("alignment_accepted", "a", "b"))
        link.telemetry = self.telemetry()
        for _ in range(8):
            self.assertTrue(link.alignment_command("alignment_accepted", "a", "b"))
        self.assertFalse(link.alignment_command("alignment_accepted", "a", "b"))
        self.assertEqual(link.commands.get_nowait()["session"], "test-session")
        with self.assertRaises(ValueError):
            link.alignment_command("unexpected", "a", "b")


if __name__ == "__main__":
    unittest.main()

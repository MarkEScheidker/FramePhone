"""ARCore extension validation, bounded history and cross-clock pose export."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
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

    def test_wearer_presence_is_negotiated_and_expires(self):
        state = self.telemetry()
        link = PhoneLink(None, None, None)
        link.telemetry = state
        link.profile = dict(profile(), headset_presence_v1=True)
        link.headset_presence(True, 1_000_000_000)
        self.assertEqual(link.presence_message(1_010_000_000),
                         {"type": "headset_presence", "session": "test-session", "worn": True})
        self.assertFalse(link.presence_message(2_000_000_001)["worn"])
        self.assertFalse(link.presence_message(999_999_999)["worn"])
        link.headset_presence(False, 2_000_000_000)
        self.assertFalse(link.presence_message(2_000_000_001)["worn"])
        link.profile = profile()
        self.assertIsNone(link.presence_message(2_000_000_001))

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

    def test_width_height_profiles_and_automatic_marker_capability(self):
        capabilities = dict(profile(), automatic_marker_v1=True)
        capabilities["dimensions"] = {"width_m": .075, "height_m": .16}
        state = Telemetry(capabilities)
        self.assertEqual(state.snapshot(0)["dimensions"], (.075, .16))
        self.assertTrue(state.snapshot(0)["automatic_marker"])
        self.assertEqual(Telemetry(profile()).dimensions, (.075, .16))
        self.assertFalse(Telemetry(profile()).snapshot(0)["automatic_marker"])

    def test_capture_clock_bias_corrected_gyro_and_compact_live_packet(self):
        from test_phone_link import batch
        state = self.telemetry()
        state.clock_reply({"session": "test-session", "h0": 1_900_000_000,
                           "p1": 900_500_000, "p2": 900_500_000}, 1_901_000_000, {1_900_000_000})
        for i in range(8):
            pose = dict(pose_message(i+1, 1_000_000_000+i*10_000_000), marker_required=False,
                        capture_t_ns=980_000_000+i*10_000_000,
                        capture_time_source="camera2_realtime_center_exposure")
            state.receive(pose, 2_000_000_000+i*10_000_000)
        gyro = batch()
        gyro["samples"][0].update(v=[.1, .2, .3], bias=[.01, .02, .03])
        state.receive(gyro, 2_080_000_000)
        packet = state.pose_packet(2_080_000_000, compact=True)
        self.assertEqual(len(packet["poses"]), 6)
        self.assertEqual(len(state.arcore_poses), 8)
        self.assertEqual(packet["poses"][-1]["pose_host_t_ns"], 2_050_000_000)
        self.assertEqual(packet["poses"][-1]["host_t_ns"], 2_070_000_000)
        for actual, expected in zip(packet["gyro"][0]["w_rad_s"], [.09, .18, .27]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(packet["pose_hz"], 100)
        state.clock_reply({"session": "test-session", "h0": 2_100_000_000,
                           "p1": 5_100_500_000, "p2": 5_100_500_000}, 2_101_000_000, {2_100_000_000})
        self.assertFalse(state.arcore_poses, "sleep clock jumps must discard old prediction history")
        self.assertFalse(state.gyro_history)

    def test_unverified_or_inconsistent_capture_clock_rejected(self):
        for fields in ({"capture_t_ns": 900_000_000},
                       {"capture_t_ns": 1_000_000_001, "capture_time_source": "camera2_realtime_center_exposure"},
                       {"capture_t_ns": 700_000_000, "capture_time_source": "camera2_realtime_center_exposure"}):
            with self.assertRaises(ValueError):
                self.telemetry().receive(dict(pose_message(), **fields), 2_000_000_000)

    def test_bluetooth_clock_allows_64ms_rtt_but_disables_gyro_prediction(self):
        radio = SimpleNamespace(authorize=lambda *_: None, send_tracking=lambda *_: False, revoke=lambda *_: None)
        link = PhoneLink(None, None, None, bluetooth=radio)
        link.start_bluetooth(dict(profile(), arcore_pose_v1=True))
        try:
            state = link.telemetry
            h0 = 1_900_000_000
            state.clock_reply(dict(session='test-session', h0=h0, p1=h0+32_000_000,
                                   p2=h0+32_000_000), h0+64_000_000, {h0})
            state.receive(dict(pose_message(), marker_required=False, capture_t_ns=980_000_000,
                               capture_time_source='camera2_realtime_center_exposure'), 2_000_000_000)
            state.gyro_history.append(dict(t_ns=1_000_000_000, w_rad_s=[1, 0, 0]))
            packet = state.pose_packet(2_000_000_000)
            self.assertTrue(packet['clock_valid'])
            self.assertEqual(packet['gyro'], [], 'high RTT must not enable IMU prediction')
            state.probes.clear()
            state.clock_reply(dict(session='test-session', h0=h0, p1=h0+41_000_000,
                                   p2=h0+41_000_000), h0+82_000_000, {h0})
            self.assertFalse(state.pose_packet(2_000_000_000)['clock_valid'])
        finally:
            link.stop()

    def test_source_sequence_rate_distinguishes_skipped_delivery(self):
        state = self.telemetry()
        state.receive(pose_message(1, 1_000_000_000), 2_000_000_000)
        state.receive(pose_message(3, 1_020_000_000), 2_020_000_000)
        packet = state.pose_packet(2_020_000_000)
        self.assertEqual(packet["pose_hz"], 50)
        self.assertEqual(packet["source_hz"], 100)

    def test_independent_gyro_requires_fresh_matching_tracking_pose(self):
        state = self.telemetry()
        link = PhoneLink(None, None, None)
        link.ble_telemetry = state
        pose = dict(pose_message(), marker_required=False)
        link.receive_bluetooth(pose, [], 2_000_000_000)
        message = dict(type='gyro_samples', session='test-session', generation='anchor-1', acquisition='scan-1')
        samples = [dict(t_ns=1_005_000_000, w_rad_s=[.1, .2, .3]),
                   dict(t_ns=1_010_000_000, w_rad_s=[.2, .3, .4])]
        link.receive_bluetooth(message, samples, 2_010_000_000)
        link.receive_bluetooth(message, samples, 2_020_000_000)
        self.assertEqual(len(state.gyro_history), 2, 'overlapping batches must not duplicate samples')
        self.assertEqual(state.arcore_received_ns, 2_000_000_000, 'gyro must not refresh the ARCore pose')
        self.assertEqual(state.arcore_poses[-1]['seq'], 1)
        new = [dict(t_ns=1_020_000_000, w_rad_s=[0, 0, 0])]
        for bad in (dict(message, session='other'), dict(message, generation='old'),
                    dict(message, acquisition='old')):
            link.receive_bluetooth(bad, new, 2_030_000_000)
        link.receive_bluetooth(message, new, 2_150_000_001)
        self.assertEqual(len(state.gyro_history), 2)

    def test_bluetooth_diagnostics_do_not_skip_inertial_samples(self):
        from test_phone_link import batch
        state = self.telemetry()
        link = PhoneLink(None, None, None)
        link.telemetry = link.ble_telemetry = state
        link.bluetooth_only = True
        state.receive(dict(pose_message(), marker_required=False), 2_000_000_000)
        link.receive_bluetooth(batch(timestamp=1_020_000_000), [], 2_020_000_000)
        self.assertFalse(state.gyro_history)
        message = dict(type='gyro_samples', session='test-session', generation='anchor-1', acquisition='scan-1')
        samples = [dict(t_ns=1_005_000_000, w_rad_s=[.1, .2, .3]),
                   dict(t_ns=1_010_000_000, w_rad_s=[.2, .3, .4])]
        link.receive_bluetooth(message, samples, 2_030_000_000)
        self.assertEqual([sample['t_ns'] for sample in state.gyro_history], [1_005_000_000, 1_010_000_000])

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

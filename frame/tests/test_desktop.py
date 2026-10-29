"""Check GUI handoff and bounded previews without root, cameras or a display."""
import importlib.util
import os
import queue
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

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

    def test_bluetooth_profile_starts_tracking_without_wifi(self):
        from phone_panel import PhonePanel
        from test_phone_link import profile
        panel = PhonePanel.__new__(PhonePanel)
        panel.parent = Mock()
        panel.store = Mock()
        panel.bluetooth = Mock(status='Bluetooth secure')
        panel.bluetooth.send_tracking.return_value = False
        panel.events = queue.Queue()
        panel.link = panel.worker = panel.pairing_request = None
        panel.closed = panel.forget_pending = panel.retry_enabled = False
        panel.retry_timer = panel.bluetooth_endpoint = None
        panel.status = Mock()
        panel.bluetooth_status = Mock()
        panel.pairing_panel = Mock()
        panel.geometry = Mock()
        panel.health = Mock()
        panel.rows = {name: Mock() for name in ('gyro', 'accel', 'mag')}
        panel.events.put(('bluetooth_tracking_profile', dict(profile(), arcore_pose_v1=True)))
        panel.tick()
        link = panel.link
        self.assertTrue(link.bluetooth_only)
        self.assertIsNone(panel.worker)
        panel.bluetooth.authorize.assert_called_once()
        panel.events.put(('bluetooth_tracking_lost', None))
        panel.tick()
        self.assertTrue(link.stopped.is_set())
        self.assertIsNone(panel.link)

    def test_fixed_front_pair_requires_matching_cameras(self):
        self.assertEqual(front.FRONT_CAMERAS,
                         (("slam_left", "og01a1b_4-0060_video3"),
                          ("slam_right", "og01a1b_4-0036_video0")))
        factories = {name: {"width": 1056, "height": 1024} for name, _ in front.FRONT_CAMERAS}
        streams = {name: {"width": 1056, "height": 1024} for _, name in front.FRONT_CAMERAS}
        front.validate_front_cameras(factories, streams)
        with self.assertRaisesRegex(ValueError, "Front right stream"):
            front.validate_front_cameras(factories, {front.FRONT_CAMERAS[0][1]: streams[front.FRONT_CAMERAS[0][1]]})
        streams[front.FRONT_CAMERAS[1][1]] = {"width": 640, "height": 640}
        with self.assertRaisesRegex(ValueError, "dimensions"):
            front.validate_front_cameras(factories, streams)

    def test_host_tools_do_not_inherit_bundled_libraries(self):
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundled", "LD_PRELOAD": "bad.so", "PYTHONHOME": "/bundled", "TK_LIBRARY": "/bundled", "DISPLAY": ":99", "FRAMEPHONE_LOADER": "/bundled"}):
            env = app.host_environment()
            self.assertEqual(env["DISPLAY"], ":99")
            self.assertFalse(any(k.startswith(("LD_", "PYTHON", "TK_", "FRAMEPHONE_")) for k in env))

    def test_idle_camera_work_requires_fresh_phone_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            window = app.Window.__new__(app.Window)
            window.capture_request = Path(directory)/"capture-active"
            window.capture_active = False
            window.status = SimpleNamespace(set=lambda value: None)
            window.closing = False
            state = {}
            window.phone_panel = SimpleNamespace(link=SimpleNamespace(snapshot=lambda: state))
            window.tracking_panel = SimpleNamespace(handoff_active=False, busy=False,
                parent=SimpleNamespace(winfo_ismapped=lambda: True))
            window.show_views = SimpleNamespace(get=lambda: True)
            window.preview_updated = [0, 0]
            calls = []
            window.preview_reader = SimpleNamespace(update=lambda *args: calls.append(args))
            window.root = SimpleNamespace(after=lambda *args: None)
            with patch.dict(sys.modules, {"tkinter": SimpleNamespace(TclError=RuntimeError)}):
                window.update_previews()
            self.assertFalse(window.capture_request.exists())
            self.assertTrue(all(not enabled for _, _, enabled in calls))
            for state in ({"marker_displayed": False, "marker_state_fresh": True},
                          {"marker_displayed": True, "marker_state_fresh": False}):
                self.assertFalse(window.marker_active())
            state = {"marker_displayed": True, "marker_state_fresh": True}
            self.assertTrue(window.marker_active())
            window.camera_demand(True)
            self.assertTrue(window.capture_request.exists())
            window.tracking_panel.handoff_active = True
            self.assertFalse(window.marker_active())
            window.camera_demand(False)
            self.assertFalse(window.capture_request.exists())

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
            struct.pack_into("<Q", data, 40, 0)  # Broker cleanly stopped.
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                reader.preview(path, "test")
            path.write_bytes(b"truncated")
            with self.assertRaises(ValueError):
                reader.preview(path, "test")


if __name__ == "__main__":
    unittest.main()

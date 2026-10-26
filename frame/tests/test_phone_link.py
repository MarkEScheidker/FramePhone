"""Real TLS socket tests plus protocol, authentication and sensor-loss diagnostics."""
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from phone_link import (MAX_MESSAGE, PairingStore, PhoneLink, Telemetry, discover,
                        DISCOVERY, PORT, fingerprint, pairing_fingerprint, read_message, write_message)


def profile():
    return {"type": "profile", "version": 1, "session": "test-session", "name": "Test phone",
            "clock": "android_elapsed_realtime_ns", "axes": "android_natural_device",
            "dimensions": {"width_m": .075, "height_m": .16, "thickness_m": .009},
            "sensors": [{"sensor": "gyro", "available": True, "units": "rad/s", "uncalibrated": True},
                        {"sensor": "accel", "available": False}, {"sensor": "mag", "available": False}]}


def batch(seq=1, timestamp=1_000_000_000):
    return {"type": "samples", "session": "test-session", "dropped": 0,
            "samples": [{"sensor": "gyro", "seq": seq, "t_ns": timestamp, "accuracy": 3,
                         "v": [0.0, 1.0, -2.0], "bias": [0.0, 0.0, 0.0]}]}


class ProtocolTests(unittest.TestCase):
    def test_discovery_uses_packet_source_and_filters_other_services(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", PORT))
            server.settimeout(2)
            errors = []
            def reply():
                try:
                    request, source = server.recvfrom(256)
                    self.assertEqual(request, DISCOVERY)
                    for service in ("unrelated", "framephone"):
                        server.sendto(json.dumps({"service": service, "version": 1, "port": PORT,
                                                  "name": "Test phone", "host": "192.0.2.1", "pairing": True}).encode(), source)
                except BaseException as error:
                    errors.append(error)
            worker = threading.Thread(target=reply)
            worker.start()
            found = discover(timeout=.4, targets=["127.0.0.1"])
            worker.join(3)
            self.assertEqual(errors, [])
            self.assertEqual(found, [{"host": "127.0.0.1", "name": "Test phone", "pairing": True}])

    def test_bounded_framing_fragmentation_and_precise_timestamps(self):
        a, b = socket.socketpair()
        with a, b:
            a.settimeout(3)
            b.settimeout(3)
            message = {"type": "ping", "h0": 9007199254740993}
            data = json.dumps(message).encode()
            wire = struct.pack("!I", len(data)) + data
            def send():
                for byte in wire:
                    a.sendall(bytes([byte]))
            thread = threading.Thread(target=send)
            thread.start()
            self.assertEqual(read_message(b), message)
            thread.join()
            a.sendall(struct.pack("!I", MAX_MESSAGE + 1))
            with self.assertRaises(ValueError):
                read_message(b)
        self.assertEqual(fingerprint(hashlib.sha256(b"abc").hexdigest()), "BA78 16BF 8F01 CFEA")
        self.assertEqual(pairing_fingerprint("a" * 64, "b" * 64, "c" * 64), "B20D D8BD D812 E185")
        self.assertNotEqual(pairing_fingerprint("a" * 64, "d" * 64, "c" * 64), "B20D D8BD D812 E185")
        with self.assertRaises(ValueError):
            pairing_fingerprint("a" * 64, "b" * 64, "bad")

    def test_rates_gaps_stale_sensors_and_clock_mapping(self):
        state = Telemetry(profile())
        state.receive(batch(), 2_000_000_000)
        state.receive(batch(3, 1_010_000_000), 2_010_000_000)
        pending = {1_900_000_000}
        state.clock_reply({"session": "test-session", "h0": 1_900_000_000,
                           "p1": 900_500_000, "p2": 900_500_000}, 1_901_000_000, pending)
        view = state.snapshot(2_010_000_000)
        self.assertEqual(view["gaps"], 1)
        self.assertEqual(view["rows"]["gyro"]["hz"], 100)
        self.assertAlmostEqual(view["rows"]["gyro"]["age_ms"], 0)
        self.assertFalse(view["rows"]["mag"]["available"])
        self.assertFalse(state.snapshot(4_000_000_000)["rows"]["gyro"]["live"])
        self.assertEqual(pending, set())

    def test_invalid_session_vectors_order_and_clock_replay(self):
        for mutation in (lambda m: m.update(session="old"),
                         lambda m: m["samples"][0].update(v=[float("nan"), 0, 0]),
                         lambda m: m["samples"][0].update(t_ns=1.5),
                         lambda m: m["samples"][0].update(seq=0),
                         lambda m: m["samples"][0].update(sensor="mag")):
            with self.subTest(mutation=mutation):
                state, message = Telemetry(profile()), batch()
                mutation(message)
                with self.assertRaises(ValueError):
                    state.receive(message, 1)
        state = Telemetry(profile())
        state.receive(batch(), 1)
        with self.assertRaises(ValueError):
            state.receive(batch(), 2)
        invalid = batch(2, 1_005_000_000)
        invalid["dropped"] = 2
        state.receive(invalid, 3)
        with self.assertRaises(ValueError):
            state.receive(batch(3, 1_010_000_000), 4)
        with self.assertRaises(ValueError):
            state.clock_reply({"session": "test-session", "h0": 1, "p1": 1, "p2": 2}, 3, set())

    def test_private_persistence_and_revocation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PairingStore(Path(folder) / "paired.json")
            self.assertIsNone(store.load())
            record = {"pin": "a" * 64, "credential": "b" * 64, "host": "127.0.0.1"}
            store.save(record)
            self.assertEqual(store.load(), record)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            os.chmod(store.path, 0o644)
            with self.assertRaises(ValueError):
                store.load()
            store.forget()
            self.assertIsNone(store.load())

    def test_phone_errors_are_actionable_without_echoing_peer_details(self):
        for code, expected in (("pairing_closed", "expired"), ("authentication_failed", "rejected"),
                               ("unknown", "Check the phone")):
            a, b = socket.socketpair()
            with a, b:
                write_message(a, {"type": "error", "code": code, "detail": "secret must not appear"})
                with self.assertRaises(ValueError) as raised:
                    read_message(b)
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("secret", str(raised.exception))


class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-nodes", "-keyout", str(cls.root / "key.pem"), "-out", str(cls.root / "cert.pem"),
                        "-days", "1", "-subj", "/CN=FramePhone test"], check=True, capture_output=True)
        der = ssl.PEM_cert_to_DER_cert((cls.root / "cert.pem").read_text())
        cls.pin = hashlib.sha256(der).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def exercise(self, pair=True, wrong_pin=False, approve=True, reject_credential=False, record=False, marker=False, arcore=False, presence=False):
        errors, received, notices = [], [], []
        ready = threading.Event()
        control_received = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            store = PairingStore(Path(directory) / "pairing.json")
            if not pair:
                store.save({"pin": "0" * 64 if wrong_pin else self.pin, "credential": "a" * 64, "host": "127.0.0.1"})
            def confirm(code, stopped):
                self.assertEqual(code, pairing_fingerprint(self.pin, received[0]["nonce"], "c" * 64))
                return approve
            recording_path = Path(directory) / "telemetry.jsonl"
            def notify(kind, value):
                notices.append((kind, value))
                if record and kind == "status" and value.startswith("Connected"):
                    client.start_recording(recording_path)
            client = PhoneLink(store, notify, confirm)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            port = listener.getsockname()[1]
            def server():
                try:
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
                    ctx.load_cert_chain(str(self.root / "cert.pem"), str(self.root / "key.pem"))
                    with listener, ctx.wrap_socket(listener.accept()[0], server_side=True) as conn:
                        conn.settimeout(5)
                        if wrong_pin:
                            self.assertEqual(conn.recv(1), b"")  # No credential, or even hello, leaked.
                            return
                        hello = read_message(conn)
                        received.append(hello)
                        if pair:
                            self.assertEqual(hello["mode"], "pair")
                            write_message(conn, {"type": "pairing", "nonce": "c" * 64})
                            if not approve:
                                self.assertEqual(conn.recv(1), b"")
                                return
                            self.assertEqual(read_message(conn), {"type": "confirm", "accepted": True})
                            write_message(conn, {"type": "paired", "credential": "a" * 64})
                        else:
                            self.assertEqual(hello["credential"], "a" * 64)
                            if reject_credential:
                                return
                        capabilities = profile()
                        if arcore:
                            capabilities["arcore_pose_v1"] = True
                        if presence:
                            capabilities["headset_presence_v1"] = True
                        write_message(conn, capabilities)
                        if presence:
                            self.assertEqual(read_message(conn), {"type": "headset_presence",
                                             "session": "test-session", "worn": False})
                        ping = read_message(conn)
                        phone_time = time.monotonic_ns() + 1_000_000_000
                        write_message(conn, {"type": "pong", "session": "test-session", "h0": ping["h0"],
                                             "p1": phone_time, "p2": phone_time})
                        write_message(conn, batch(timestamp=phone_time))
                        if marker:
                            write_message(conn, {"type": "marker_state", "session": "test-session", "displayed": True,
                                "fiducial": {"family": "tag36h11", "id": 0, "black_edge_m": .06,
                                    "origin": "black_square_center", "axes": "right_up_front", "size_source": "android_display_dpi",
                                    "screen_width_px": 1080, "screen_height_px": 2400, "black_edge_px": 864}})
                        ready.set()
                        if presence:
                            time.sleep(.1)
                            write_message(conn, batch(2, time.monotonic_ns()+1_000_000_000))
                            self.assertEqual(read_message(conn), {"type": "headset_presence",
                                             "session": "test-session", "worn": True})
                            control_received.set()
                        if arcore:
                            from test_arcore_link import pose_message
                            for seq in range(1, 21):
                                write_message(conn, pose_message(seq, time.monotonic_ns()+1_000_000_000))
                                time.sleep(.02)
                            self.assertEqual(read_message(conn), {
                                "type": "alignment_accepted", "session": "test-session",
                                "generation": "anchor-1", "acquisition": "scan-1"})
                            control_received.set()
                        # Keep the session open while the test checks the live snapshot.
                        conn.recv(1)
                except BaseException as error:
                    errors.append(error)
            server_thread = threading.Thread(target=server, daemon=True)
            client_thread = threading.Thread(target=client.run, args=("127.0.0.1", pair, port), daemon=True)
            server_thread.start()
            client_thread.start()
            if not wrong_pin and approve and not reject_credential:
                self.assertTrue(ready.wait(5))
                deadline = time.monotonic() + 3
                snapshot = None
                while time.monotonic() < deadline:
                    snapshot = client.snapshot()
                    if snapshot and snapshot["count"] == 1:
                        break
                    time.sleep(.01)
                self.assertEqual(snapshot["count"], 1)
                self.assertTrue(snapshot["rows"]["gyro"]["live"])
                self.assertIsNotNone(snapshot["rtt_ms"])
                self.assertEqual(store.load()["pin"], self.pin)
                if marker:
                    while not snapshot.get("marker_displayed") and time.monotonic() < deadline:
                        time.sleep(.01)
                        snapshot = client.snapshot()
                    self.assertTrue(snapshot["marker_displayed"])
                    self.assertTrue(snapshot["marker_state_fresh"])
                    self.assertEqual(snapshot["fiducial"]["black_edge_px"], 864)
                if presence:
                    client.headset_presence(True, time.monotonic_ns())
                    self.assertTrue(control_received.wait(3))
                if arcore:
                    self.assertTrue(client.alignment_command("alignment_accepted", "anchor-1", "scan-1"))
                    self.assertTrue(control_received.wait(3))
                    self.assertEqual(client.snapshot()["arcore"]["poses"][-1]["seq"], 20)
                client.stop()
            client_thread.join(6)
            server_thread.join(6)
            self.assertFalse(client_thread.is_alive())
            self.assertFalse(server_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertIsNone(client.snapshot())
            if wrong_pin or reject_credential or not approve:
                self.assertTrue(any(kind == "error" for kind, _ in notices))
            if pair and not approve:
                self.assertIsNone(store.load())
            if record:
                entries = [json.loads(line) for line in recording_path.read_text().splitlines()]
                self.assertEqual([entry["message"]["type"] for entry in entries[:-1]],
                                 ["profile", "pong", "samples"] + (["marker_state"] if marker else []) + (["arcore_pose"]*20 if arcore else []))
                self.assertTrue(entries[-1]["end"])
                self.assertNotIn("credential", recording_path.read_text())
                self.assertTrue(all(type(entry["received_host_monotonic_ns"]) is int for entry in entries[:-1]))

    def test_pair_and_live_telemetry(self):
        self.exercise()

    def test_arcore_poses_alignment_command_and_recording(self):
        self.exercise(pair=False, arcore=True, record=True)

    def test_authenticated_wearer_presence_defaults_off_then_follows_monitor(self):
        self.exercise(pair=False, presence=True)

    def test_pinned_reconnect(self):
        self.exercise(pair=False)

    def test_authenticated_fullscreen_marker_state_and_recording(self):
        self.exercise(pair=False, marker=True, record=True)

    def test_opt_in_recording_receives_validated_tls_evidence(self):
        self.exercise(record=True)

    def test_changed_identity_never_receives_credential(self):
        self.exercise(pair=False, wrong_pin=True)

    def test_rejected_pair_is_not_saved(self):
        self.exercise(approve=False)

    def test_revoked_credential_does_not_stream(self):
        self.exercise(pair=False, reject_credential=True)

    def test_immediate_eof_identifies_tls_handshake_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            def close_without_handshake():
                with listener, listener.accept()[0] as connection:
                    connection.settimeout(5)
                    header = b""
                    while len(header) < 5:
                        header += connection.recv(5 - len(header))
                    remaining = int.from_bytes(header[3:5], "big")
                    while remaining:
                        remaining -= len(connection.recv(remaining))
            server = threading.Thread(target=close_without_handshake)
            server.start()
            notices = []
            client = PhoneLink(PairingStore(Path(directory) / "pairing.json"),
                               lambda kind, value: notices.append((kind, value)), lambda *_: True)
            port = listener.getsockname()[1]
            client.run("127.0.0.1", pair=True, port=port)
            server.join(5)
            self.assertFalse(server.is_alive())
            errors = [value for kind, value in notices if kind == "error"]
            self.assertEqual(len(errors), 1)
            self.assertIn("TLS handshake", errors[0])
            self.assertIn("phone APK", errors[0])
            self.assertIsNone(client.store.load())


if __name__ == "__main__":
    unittest.main()

"""Actual Tk Bluetooth-only connection UI against a pinned loopback TLS phone."""
from pathlib import Path
from types import SimpleNamespace
import select
import socket
import ssl
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from phone_link import PORT, read_message, write_message
from phone_panel import PhonePanel
from test_phone_link import TLSTests, profile, batch


def until(root, panel, predicate):
    deadline = time.monotonic()+6
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError(panel.status.get())


def connected_ui():
    TLSTests.setUpClass()
    errors, stop = [], threading.Event()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", PORT))
    listener.listen(1)
    listener.settimeout(5)

    def phone():
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(str(TLSTests.root / "cert.pem"), str(TLSTests.root / "key.pem"))
            with listener, context.wrap_socket(listener.accept()[0], server_side=True) as conn:
                conn.settimeout(5)
                hello = read_message(conn)
                assert hello["mode"] == "reconnect" and hello["credential"] == "b"*64
                write_message(conn, profile())
                sequence = 0
                while not stop.is_set():
                    if conn.pending() or select.select([conn], [], [], .01)[0]:
                        ping = read_message(conn)
                        now = time.monotonic_ns()
                        write_message(conn, {"type": "pong", "session": "test-session", "h0": ping["h0"], "p1": now, "p2": now})
                    sequence += 1
                    write_message(conn, batch(sequence, time.monotonic_ns()))
        except OSError:
            if not stop.is_set():
                errors.append("TLS phone disconnected unexpectedly")
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=phone, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            root.report_callback_exception = lambda *error: errors.append(error)
            radio = SimpleNamespace(status="Bluetooth authenticated", revoke=lambda *_: None, forget=lambda: panel.store.forget())
            panel = PhonePanel(root, Path(directory), bluetooth=radio)
            try:
                # Simulate only the authenticated BLE enrollment boundary. The
                # real pinned TLS exchange and telemetry rendering run unchanged.
                panel.store.save({"pin": TLSTests.pin, "credential": "b"*64, "host": "127.0.0.1", "bluetooth": True})
                panel.startup()
                assert panel.worker is None, "startup used a cached LAN route before Bluetooth"
                panel.notify("bluetooth_endpoint", "127.0.0.1")
                until(root, panel, lambda: "Hz" in panel.rows["gyro"].get())
                assert panel.status.get() == "Wi-Fi connected"
                assert "Bluetooth" in panel.bluetooth_status.get()
                assert "75.0" in panel.geometry.get()
                assert "Unavailable" in panel.rows["mag"].get()
                def widgets(parent):
                    return [child for direct in parent.winfo_children() for child in [direct, *widgets(direct)]]
                controls = widgets(root)
                assert not any(w.winfo_class() in ("TEntry", "TCombobox") for w in controls)
                buttons = [w.cget("text") for w in controls if w.winfo_class() == "TButton" and w.winfo_ismapped()]
                assert buttons == ["Forget phone"], buttons
                request = dict(passkey="012345", accepted=False, event=threading.Event())
                panel.notify("bluetooth_pairing", request)
                until(root, panel, lambda: panel.pairing_panel.winfo_ismapped())
                assert panel.pairing_number.get() == "012345"
                panel.answer_pairing(True)
                assert request["event"].is_set() and request["accepted"]
                assert not panel.pairing_panel.winfo_ismapped()
                replacement = dict(kind="replace", passkey="", accepted=False, event=threading.Event())
                panel.notify("bluetooth_pairing", replacement)
                until(root, panel, lambda: panel.pairing_panel.winfo_ismapped())
                assert panel.pairing_accept.cget("text") == "Replace phone"
                panel.answer_pairing(False)
                assert replacement["event"].is_set() and not replacement["accepted"]
                assert not panel.link.stopped.is_set(), "rejection disconnected the working phone"
                stop.set()
                panel.forget()
                until(root, panel, lambda: panel.store.load() is None and not panel.worker.is_alive())
                assert not errors, errors
                print("Bluetooth-only UI, automatic pinned TLS, sensor telemetry and Forget passed")
            finally:
                panel.close()
                root.destroy()
    finally:
        stop.set()
        listener.close()
        worker.join(6)
        TLSTests.tearDownClass()


def automatic_recovery():
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        panel = PhonePanel(root, Path(directory), bluetooth=SimpleNamespace(status="Bluetooth connected"))
        panel.store.save({"pin": "a"*64, "credential": "b"*64, "host": "192.168.1.10", "bluetooth": True})
        attempts = []

        class Link:
            def __init__(self, store, notify, confirm, bluetooth=None):
                self.notify, self.stopped = notify, threading.Event()
                self.retryable = True
            def snapshot(self): return None
            def stop(self): self.stopped.set()
            def run(self, host, pair):
                attempts.append((host, pair))
                assert not pair
                if len(attempts) == 1:
                    # Failure before the first successful TLS connection must
                    # retry too; an unlock provides a new authenticated route.
                    self.notify("error", "network unreachable")
                else:
                    self.notify("connected", host)
                    self.stopped.wait(5)
                self.notify("ended", "Disconnected")

        try:
            with patch("phone_panel.PhoneLink", Link):
                panel.startup()
                assert not attempts
                panel.notify("bluetooth_endpoint", "192.168.1.10")
                until(root, panel, lambda: panel.retry_timer is not None)
                panel.notify("bluetooth_endpoint", "192.168.1.20")
                until(root, panel, lambda: panel.status.get() == "Wi-Fi connected")
                assert attempts == [("192.168.1.10", False), ("192.168.1.20", False)]
                old_link = panel.link
                panel.notify("bluetooth_replaced", None)
                panel.notify("bluetooth_endpoint", "192.168.1.30")
                until(root, panel, lambda: len(attempts) == 3 and panel.status.get() == "Wi-Fi connected")
                assert old_link.stopped.is_set(), "replacement left the old authenticated session alive"
                assert attempts[-1] == ("192.168.1.30", False)
                panel.link.retryable = False
                panel.schedule_retry()
                assert not panel.retry_enabled and panel.retry_timer is None
                panel.close()
                until(root, panel, lambda: not panel.worker.is_alive())
                assert not errors, errors
                print("Initial Wi-Fi failure retry, unlock route refresh and identity-failure retry stop passed")
        finally:
            if not panel.closed:
                panel.close()
            root.destroy()


if __name__ == "__main__":
    connected_ui()
    automatic_recovery()

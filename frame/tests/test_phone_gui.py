"""Run with xvfb-run: actual Tk pairing/telemetry UI against a local TLS phone."""
from pathlib import Path
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


def main():
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
                assert read_message(conn)["mode"] == "pair"
                write_message(conn, {"type": "pairing", "nonce": "c" * 64})
                assert read_message(conn) == {"type": "confirm", "accepted": True}
                write_message(conn, {"type": "paired", "credential": "b" * 64})
                write_message(conn, profile())
                sequence = 0
                while not stop.is_set():
                    if conn.pending() or select.select([conn], [], [], .01)[0]:
                        ping = read_message(conn)
                        now = time.monotonic_ns()
                        write_message(conn, {"type": "pong", "session": "test-session", "h0": ping["h0"], "p1": now, "p2": now})
                    sequence += 1
                    write_message(conn, batch(sequence, time.monotonic_ns()))
        except (OSError, ConnectionError):
            if not stop.is_set():
                errors.append("TLS phone disconnected unexpectedly")
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=phone, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            root.geometry("1000x850")
            root.report_callback_exception = lambda *error: errors.append(error)
            panel = PhonePanel(root, Path(directory))
            def until(predicate):
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    root.update()
                    if predicate():
                        return
                    time.sleep(.01)
                raise AssertionError(panel.status.get())
            try:
                panel.host.set("127.0.0.1")
                panel.pair_button.invoke()
                until(lambda: panel.approval is not None)
                assert panel.confirmation.winfo_ismapped()
                assert panel.confirmation.winfo_y() < root.winfo_height() - 100
                assert len(panel.comparison.get().split()) == 4
                panel.answer(True)
                until(lambda: "Hz" in panel.rows["gyro"].get())
                assert "75.0" in panel.geometry.get()
                assert "Unavailable" in panel.rows["mag"].get()
                assert panel.store.load()["pin"] == TLSTests.pin
                stop.set()
                panel.forget()
                until(lambda: panel.rows["gyro"].get() == "Not connected")
                until(lambda: not panel.worker.is_alive())
                until(lambda: panel.store.load() is None)
                assert panel.store.load() is None
                assert not errors, errors
                print("Tk pairing, fingerprint approval, TLS telemetry, missing sensor, disconnect and Forget passed")
            finally:
                panel.close()
                root.destroy()
    finally:
        stop.set()
        listener.close()
        worker.join(6)
        TLSTests.tearDownClass()


def automatic_reconnect():
    """Discovery tries the saved endpoint first and never enrolls a new phone."""
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        panel = PhonePanel(root, Path(directory))
        panel.store.save({"pin": "a"*64, "credential": "b"*64, "host": "127.0.0.10"})
        panel.host.set("127.0.0.10")
        attempts = []
        class Link:
            def __init__(self, store, notify, confirm):
                self.notify = notify
                self.stopped = threading.Event()
            def snapshot(self):
                return None
            def stop(self):
                self.stopped.set()
            def run(self, host, pair):
                attempts.append((host, pair))
                assert not pair, "startup tried to enroll an untrusted phone"
                if host != "127.0.0.30":
                    self.notify("error", "Saved identity did not match")
                else:
                    self.notify("connected", host)
                    self.notify("status", "Connected")
                    self.stopped.wait(5)
                self.notify("ended", "Disconnected")
        def until(predicate):
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                root.update()
                if predicate(): return
                time.sleep(.01)
            raise AssertionError(panel.status.get())
        phones = [{"host": host, "name": "Phone", "pairing": True}
                  for host in ("127.0.0.20", "127.0.0.30", "127.0.0.30")]
        try:
            with patch("phone_panel.PhoneLink", Link), patch("phone_panel.discover", return_value=phones):
                panel.startup()
                until(lambda: panel.status.get() == "Connected")
                assert attempts == [("127.0.0.10", False), ("127.0.0.20", False), ("127.0.0.30", False)]
                assert not panel.auto_hosts and not panel.approval
                panel.disconnect()
                until(lambda: not panel.worker.is_alive())
                for _ in range(20):
                    root.update()
                    time.sleep(.01)
                assert len(attempts) == 3, "manual disconnect restarted automatic connection"
                # Cancelling discovery also cancels its pending auto-connect.
                release = threading.Event()
                def delayed_discovery():
                    release.wait(2)
                    return phones
                with patch("phone_panel.discover", delayed_discovery):
                    panel.startup()
                    panel.disconnect()
                    release.set()
                    until(lambda: not panel.searching)
                assert len(attempts) == 3
                panel.host.set("")
                panel.store.save({"pin": "a"*64, "credential": "b"*64})
                with patch("phone_panel.discover", return_value=[]):
                    panel.startup()
                    until(lambda: "Saved phone unavailable" in panel.status.get())
                assert not panel.auto_connecting and len(attempts) == 3
            print("Automatic saved-phone discovery, endpoint fallback, no enrollment and cancellation passed")
        finally:
            panel.close()
            if panel.worker: panel.worker.join(1)
            root.destroy()


def transport_recovery():
    """A previously authenticated peer reconnects after sleep/network loss without enrollment."""
    with tempfile.TemporaryDirectory() as directory:
        root = tk.Tk()
        panel = PhonePanel(root, Path(directory))
        panel.store.save({"pin":"a"*64,"credential":"b"*64,"host":"127.0.0.1"})
        panel.host.set("127.0.0.1")
        attempts=[]
        class Link:
            def __init__(self, store, notify, confirm):
                self.notify=notify
                self.stopped=threading.Event()
                self.retryable=False
            def snapshot(self): return None
            def stop(self): self.stopped.set()
            def run(self, host, pair):
                attempts.append((host,pair))
                assert not pair
                self.notify('connected',host)
                if len(attempts)==1:
                    self.retryable=True
                    self.notify('ended','Disconnected')
                else:
                    self.notify('status','Recovered')
                    self.stopped.wait(5)
                    self.notify('ended','Disconnected')
        def until(predicate):
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                root.update()
                if predicate(): return
                time.sleep(.01)
            raise AssertionError(panel.status.get())
        try:
            with patch('phone_panel.PhoneLink',Link):
                panel.connect()
                until(lambda: panel.status.get()=='Recovered')
                assert attempts==[('127.0.0.1',False)]*2
                panel.disconnect()
                until(lambda: not panel.worker.is_alive())
                assert panel.retry_timer is None and not panel.retry_enabled
                # A pin/protocol failure is not treated as a transient network loss.
                panel.retry_enabled=True
                panel.link.stopped.clear()
                panel.link.retryable=False
                panel.schedule_retry()
                assert not panel.retry_enabled and panel.retry_timer is None
            print('Authenticated transport-loss recovery, manual cancellation and identity-failure retry stop passed')
        finally:
            panel.close()
            root.destroy()


if __name__ == "__main__":
    main()
    automatic_reconnect()
    transport_recovery()

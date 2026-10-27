"""Bluetooth pairing status, automatic pinned Wi-Fi connection and telemetry."""
import queue
import threading

from phone_link import PairingStore, PhoneLink, SENSORS


class PhonePanel:
    def __init__(self, parent, config_dir, bluetooth=None):
        import tkinter as tk
        from tkinter import ttk
        self.parent, self.bluetooth = parent, bluetooth
        self.events = queue.Queue(maxsize=64)
        self.link = self.worker = None
        self.pairing_request = None
        self.closed = self.forget_pending = False
        self.bluetooth_endpoint = None
        self.retry_enabled = False
        self.retry_delay = 1
        self.retry_timer = None
        self.store = PairingStore(config_dir / "phone-pairing.json")
        self.host = tk.StringVar()  # Authenticated route; never editable in the UI.
        self.status = tk.StringVar(value="Pair this headset from FramePhone on your phone.")
        self.bluetooth_status = tk.StringVar(value="Bluetooth starting…")
        self.geometry = tk.StringVar(value="")
        self.health = tk.StringVar(value="")
        self.rows = {}
        self.pairing_number = tk.StringVar()
        panel = ttk.LabelFrame(parent, text="Phone", padding=6)
        panel.pack(fill="x")
        header = ttk.Frame(panel)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.bluetooth_status, wraplength=550).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="Forget phone", command=self.forget).pack(side="right")
        ttk.Label(panel, textvariable=self.status, wraplength=660).pack(anchor="w")
        self.pairing_panel = ttk.LabelFrame(panel, text="Pair phone with Steam Frame", padding=6)
        ttk.Label(self.pairing_panel, textvariable=self.pairing_number, font=("monospace", 20, "bold")).pack(anchor="w")
        self.pairing_hint = tk.StringVar()
        ttk.Label(self.pairing_panel, textvariable=self.pairing_hint, wraplength=600).pack(anchor="w")
        self.pairing_accept = ttk.Button(self.pairing_panel, text="Numbers match", command=lambda: self.answer_pairing(True))
        self.pairing_accept.pack(side="left")
        ttk.Button(self.pairing_panel, text="Reject", command=lambda: self.answer_pairing(False)).pack(side="left", padx=6)
        self.telemetry_panel = ttk.Frame(panel)
        self.telemetry_panel.pack(fill="x")
        for col, name in enumerate(SENSORS):
            self.telemetry_panel.columnconfigure(col, weight=1, uniform="sensor")
            box = ttk.LabelFrame(self.telemetry_panel, text={"gyro": "Gyroscope", "accel": "Accelerometer", "mag": "Magnetometer"}[name]+" · "+SENSORS[name], padding=4)
            box.grid(row=0, column=col, sticky="nsew", padx=2)
            value = tk.StringVar(value="Not connected")
            self.rows[name] = value
            ttk.Label(box, textvariable=value, font=("monospace", 9), wraplength=200).pack(anchor="w")
        ttk.Label(panel, textvariable=self.geometry).pack(anchor="w")
        ttk.Label(panel, textvariable=self.health, wraplength=660).pack(anchor="w")
        self.timer = parent.after(100, self.tick)

    def notify(self, kind, value):
        if not self.closed:
            try:
                self.events.put_nowait((kind, value))
            except queue.Full:
                pass

    def answer_pairing(self, accepted):
        if self.pairing_request:
            self.pairing_request['accepted'] = accepted
            self.pairing_request['event'].set()
            self.pairing_request = None
        self.pairing_panel.pack_forget()

    def startup(self):
        self.cancel_retry()
        try:
            saved = self.store.load()
            self.status.set("Waiting for the paired phone over Bluetooth…" if saved else
                            "Pair this headset from FramePhone on your phone.")
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def connect(self):
        if self.closed or self.forget_pending or (self.worker and self.worker.is_alive()):
            return
        self.status.set("Wi-Fi connecting automatically…")
        # Enrollment is Bluetooth-only. The TLS client may reconnect solely
        # with the certificate pin/credential established by that pairing.
        self.link = PhoneLink(self.store, self.notify, lambda *_: False, bluetooth=self.bluetooth)
        self.worker = threading.Thread(target=self.link.run, args=(self.host.get(), False), daemon=True)
        self.worker.start()

    def cancel_retry(self, disable=False):
        if self.retry_timer is not None:
            self.parent.after_cancel(self.retry_timer)
            self.retry_timer = None
        if disable:
            self.retry_enabled = False

    def schedule_retry(self):
        if self.closed or not self.retry_enabled or self.retry_timer is not None:
            return
        if not self.link or self.link.stopped.is_set() or not self.link.retryable:
            self.retry_enabled = False
            return
        delay = self.retry_delay
        self.retry_delay = min(5, delay*2)
        self.status.set("Wi-Fi unavailable — retrying automatically. Keep both devices on the same network.")
        self.retry_timer = self.parent.after(int(delay*1000), self.retry_saved)

    def retry_saved(self):
        self.retry_timer = None
        if self.closed or not self.retry_enabled:
            return
        if self.worker and self.worker.is_alive():
            self.retry_timer = self.parent.after(100, self.retry_saved)
            return
        self.connect()

    def disconnect(self):
        """Internal shutdown; normal use stays connected automatically."""
        self.cancel_retry(disable=True)
        self.answer_pairing(False)
        self.bluetooth_endpoint = None
        if self.link:
            self.link.stop()

    def forget(self):
        self.forget_pending = True
        self.disconnect()
        if self.worker and self.worker.is_alive():
            self.status.set("Disconnecting and forgetting phone…")
        else:
            self.forget_saved()

    def forget_saved(self):
        try:
            if self.bluetooth:
                self.bluetooth.forget()
            else:
                self.store.forget()
            self.status.set("Phone forgotten. Forget the headset on your phone before pairing again.")
        except (OSError, ValueError) as error:
            self.status.set(str(error))
        self.forget_pending = False
        self.host.set("")

    def tick(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "bluetooth_pairing":
                self.answer_pairing(False)
                self.pairing_request = value
                kind = value.get('kind', 'bond')
                self.pairing_panel.configure(text="Pair phone with Steam Frame" if kind == 'bond' else "Confirm phone pairing")
                self.pairing_number.set(value['passkey'] if kind == 'bond' else
                                        "Replace saved phone?" if kind == 'replace' else "Connect this phone?")
                self.pairing_hint.set("Confirm this number matches your phone." if kind == 'bond' else
                                      "Approve if you reinstalled/reset the phone app or are pairing another phone." if kind == 'replace' else
                                      "This restores the app connection over the existing Bluetooth bond.")
                self.pairing_accept.configure(text="Numbers match" if kind == 'bond' else "Replace phone" if kind == 'replace' else "Connect phone")
                self.pairing_panel.pack(fill="x", pady=6, before=self.telemetry_panel)
            elif kind == "bluetooth_pairing_closed":
                if self.pairing_request is value:
                    self.answer_pairing(False)
            elif kind == "bluetooth_replaced":
                self.disconnect()
            elif kind == "bluetooth_endpoint":
                try:
                    if not self.closed and not self.forget_pending and self.store.load():
                        self.bluetooth_endpoint = value
                        self.retry_enabled = True
                except (OSError, ValueError) as error:
                    self.status.set(str(error))
            elif kind == "connected":
                if self.link and not self.link.stopped.is_set():
                    self.cancel_retry()
                    self.retry_enabled = True
                    self.retry_delay = 1
                    self.status.set("Wi-Fi connected")
            elif kind == "error":
                self.status.set("Wi-Fi connection failed: " + value)
            elif kind == "ended":
                if self.forget_pending:
                    self.forget_saved()
                else:
                    self.schedule_retry()
            elif kind == "confirm":
                value["accepted"] = False
                value["event"].set()
        if self.bluetooth_endpoint and not self.closed and not (self.worker and self.worker.is_alive()):
            self.cancel_retry()
            self.host.set(self.bluetooth_endpoint)
            self.bluetooth_endpoint = None
            self.connect()
        self.bluetooth_status.set(self.bluetooth.status if self.bluetooth else "Bluetooth unavailable")
        snapshot = self.link.snapshot() if self.link else None
        if snapshot:
            self.geometry.set("Phone: %.1f × %.1f mm" % tuple(x*1000 for x in snapshot["dimensions"][:2]))
            for name, row in snapshot["rows"].items():
                if not row["available"]:
                    text = "Unavailable on this phone"
                elif not row["live"]:
                    text = "Waiting for fresh samples"
                else:
                    xyz = " ".join(f"{axis} {v:+.3f}" for axis, v in zip("XYZ", row["sample"]["v"]))
                    age = "clock syncing" if row["age_ms"] is None else f"age ≈ {row['age_ms']:.1f} ms"
                    text = f"{xyz}\n{row['hz']:.1f} Hz · {age}"
                self.rows[name].set(text)
            transport = "Bluetooth LE" if snapshot.get("pose_transport") == "bluetooth" else "Wi-Fi backup"
            rtt = snapshot["rtt_ms"]
            clock = "clock syncing" if rtt is None else f"Wi-Fi RTT {rtt:.2f} ms"
            self.health.set(f"Pose: {transport} · {clock} · {snapshot['dropped']} sensor samples dropped")
        else:
            for row in self.rows.values():
                row.set("Not connected")
            self.geometry.set("")
            self.health.set("")
        if not self.closed:
            self.timer = self.parent.after(100, self.tick)

    def close(self):
        self.closed = True
        self.disconnect()
        self.parent.after_cancel(self.timer)

"""Tk controls for LAN pairing and live phone sensor diagnostics."""
import queue
import threading
import time

from phone_link import PairingStore, PhoneLink, SENSORS, discover


class PhonePanel:
    def __init__(self, parent, config_dir):
        import tkinter as tk
        from tkinter import ttk
        self.parent = parent
        self.events = queue.Queue(maxsize=64)
        self.link = self.worker = self.approval = None
        self.closed = self.searching = False
        self.forget_pending = False
        self.store = PairingStore(config_dir / "phone-pairing.json")
        self.host = tk.StringVar()
        self.status = tk.StringVar(value="On your phone, save dimensions and start pairing. Use the same LAN.")
        self.geometry = tk.StringVar(value="Phone dimensions arrive after connecting.")
        self.health = tk.StringVar(value="No live telemetry")
        self.comparison = tk.StringVar()
        self.phones = []
        self.rows = {}
        try:
            saved = self.store.load()
            if saved:
                self.host.set(saved.get("host", ""))
        except (OSError, ValueError) as error:
            self.status.set(str(error))
        panel = ttk.Frame(parent, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Phone telemetry", font=("sans", 22, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Pair once, then receive live gyro, accelerometer and magnetometer data.").pack(anchor="w", pady=8)
        discovery = ttk.Frame(panel)
        discovery.pack(fill="x", pady=8)
        self.find_button = ttk.Button(discovery, text="Find phones", command=self.find)
        self.find_button.pack(side="left")
        self.choices = ttk.Combobox(discovery, state="readonly", width=55)
        self.choices.pack(side="left", fill="x", expand=True, padx=10)
        self.choices.bind("<<ComboboxSelected>>", self.selected)
        address = ttk.Frame(panel)
        address.pack(fill="x")
        ttk.Label(address, text="Phone IP (manual fallback):").pack(side="left")
        ttk.Entry(address, textvariable=self.host, width=20).pack(side="left", padx=8)
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=12)
        self.pair_button = ttk.Button(buttons, text="Pair new phone", command=lambda: self.connect(True))
        self.pair_button.pack(side="left")
        self.connect_button = ttk.Button(buttons, text="Connect saved phone", command=self.connect)
        self.connect_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Disconnect", command=self.disconnect).pack(side="left")
        ttk.Button(buttons, text="Forget phone", command=self.forget).pack(side="right")
        ttk.Label(panel, textvariable=self.status, wraplength=850).pack(anchor="w", pady=8)
        self.confirmation = ttk.LabelFrame(panel, text="Verify on the physical phone", padding=12)
        ttk.Label(self.confirmation, textvariable=self.comparison, font=("monospace", 22, "bold")).pack(anchor="w")
        ttk.Label(self.confirmation, text="All four fingerprint groups must match. Approve on both screens.").pack(anchor="w", pady=8)
        ttk.Button(self.confirmation, text="Fingerprints match", command=lambda: self.answer(True)).pack(side="left")
        ttk.Button(self.confirmation, text="Reject", command=lambda: self.answer(False)).pack(side="left", padx=8)
        self.separator = ttk.Separator(panel)
        self.separator.pack(fill="x", pady=16)
        ttk.Label(panel, textvariable=self.geometry, font=("sans", 13)).pack(anchor="w")
        for name, title in (("gyro", "Gyroscope"), ("accel", "Accelerometer"), ("mag", "Magnetometer")):
            box = ttk.LabelFrame(panel, text=title, padding=10)
            box.pack(fill="x", pady=8)
            value = tk.StringVar(value="Not connected")
            self.rows[name] = value
            ttk.Label(box, textvariable=value, font=("monospace", 12), wraplength=850).pack(anchor="w")
        ttk.Label(panel, textvariable=self.health, wraplength=850).pack(anchor="w", pady=10)
        ttk.Label(panel, text="Fixed Android natural-device axes: X right, Y up, Z out of screen. "
                  "Accelerometer includes gravity. Bias values are reported separately.\n"
                  "Timing is diagnostic only; use Photo tracking for the fixed-photo stereo test. ARCore/world alignment is not implemented.",
                  wraplength=850).pack(anchor="w", pady=8)
        self.timer = parent.after(100, self.tick)

    def notify(self, kind, value):
        if not self.closed:
            try:
                self.events.put_nowait((kind, value))
            except queue.Full:
                pass

    def confirm(self, fingerprint, stopped):
        request = {"event": threading.Event(), "accepted": False, "fingerprint": fingerprint}
        self.notify("confirm", request)
        deadline = time.monotonic() + 55
        while not stopped.is_set() and time.monotonic() < deadline:
            if request["event"].wait(0.1):
                return request["accepted"]
        return False

    def answer(self, accepted):
        if self.approval:
            self.approval["accepted"] = accepted
            self.approval["event"].set()
            self.approval = None
        self.confirmation.pack_forget()

    def find(self):
        if self.searching:
            return
        self.searching = True
        self.find_button.configure(state="disabled")
        self.status.set("Searching the LAN…")
        def search():
            try:
                self.notify("phones", discover())
            except OSError:
                self.notify("phones", [])
        threading.Thread(target=search, daemon=True).start()

    def selected(self, _event=None):
        index = self.choices.current()
        if 0 <= index < len(self.phones):
            self.host.set(self.phones[index]["host"])

    def connect(self, pair=False):
        if self.worker and self.worker.is_alive():
            self.status.set("Disconnect the current phone before connecting again.")
            return
        self.link = PhoneLink(self.store, self.notify, self.confirm)
        self.worker = threading.Thread(target=self.link.run, args=(self.host.get().strip(), pair), daemon=True)
        self.worker.start()
        self.pair_button.configure(state="disabled")
        self.connect_button.configure(state="disabled")

    def disconnect(self):
        self.answer(False)
        if self.link:
            self.link.stop()
        self.status.set("Disconnected")

    def forget(self):
        # Wait for pending enrollment to finish/cancel before deleting credentials.
        if self.worker and self.worker.is_alive():
            self.forget_pending = True
            self.disconnect()
            self.status.set("Disconnecting and forgetting phone…")
            return
        self.forget_saved()

    def forget_saved(self):
        self.forget_pending = False
        try:
            self.store.forget()
            self.status.set("Local pairing removed. Use Forget headset on the phone to revoke its credential too.")
        except OSError as error:
            self.status.set(str(error))

    def tick(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in ("status", "error"):
                self.status.set(value)
            elif kind == "confirm":
                self.approval = value
                self.comparison.set(value["fingerprint"])
                self.confirmation.pack(fill="x", pady=8, before=self.separator)
            elif kind == "phones":
                self.searching, self.phones = False, value
                self.find_button.configure(state="normal")
                self.choices.configure(values=[f"{p['name']} — {p['host']}" + (" (pairing)" if p['pairing'] else "") for p in value])
                if value:
                    self.choices.current(0)
                    self.selected()
                self.status.set(f"Found {len(value)} phone(s). Select one, then Pair or Connect."
                                if value else "No phones found. Check the phone is started; enter its displayed IP if broadcast is blocked.")
            elif kind == "ended":
                self.answer(False)
                if self.forget_pending:
                    self.forget_saved()
                self.pair_button.configure(state="normal")
                self.connect_button.configure(state="normal")
        snapshot = self.link.snapshot() if self.link else None
        if snapshot:
            self.geometry.set("Phone body / case: %.1f × %.1f × %.1f mm" % tuple(x * 1000 for x in snapshot["dimensions"]))
            for name, row in snapshot["rows"].items():
                if not row["available"]:
                    text = "Unavailable on this phone"
                elif not row["live"]:
                    text = "Waiting / stale — no fresh samples"
                else:
                    sample = row["sample"]
                    xyz = "  ".join(f"{axis} {v:+9.4f}" for axis, v in zip("XYZ", sample["v"]))
                    age = "clock syncing" if row["age_ms"] is None else f"age ≈ {row['age_ms']:.1f} ms"
                    text = f"{xyz}  {SENSORS[name]}\n{row['hz']:.1f} Hz received · {age} · accuracy {sample['accuracy']}"
                    text += " · uncalibrated" if row["uncalibrated"] else " · calibrated"
                    if "bias" in sample:
                        text += "\nBias: " + ", ".join(f"{x:+.4f}" for x in sample["bias"])
                self.rows[name].set(text)
            rtt = snapshot["rtt_ms"]
            clock = "Synchronizing clocks" if rtt is None else f"Best recent RTT {rtt:.2f} ms; age uncertainty at least ±{rtt / 2:.2f} ms"
            self.health.set(f"{snapshot['count']} samples · {snapshot['gaps']} sequence gaps · {snapshot['dropped']} phone queue drops\n{clock}")
        else:
            for row in self.rows.values():
                row.set("Not connected")
            self.health.set("No live telemetry")
        if not self.closed:
            self.timer = self.parent.after(100, self.tick)

    def close(self):
        self.closed = True
        self.disconnect()
        self.parent.after_cancel(self.timer)

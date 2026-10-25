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
        self.auto_search = False
        self.auto_connecting = False
        self.auto_hosts = []
        self.auto_error = ""
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
        panel = ttk.LabelFrame(parent, text="Phone", padding=6)
        panel.pack(fill="x")
        header = ttk.Frame(panel)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.status, wraplength=550).pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="Connection", command=self.toggle_connection).pack(side="right")
        self.settings = ttk.Frame(panel)
        if not self.host.get():
            self.settings.pack(fill="x", pady=4)
        discovery = ttk.Frame(self.settings)
        discovery.pack(fill="x")
        self.find_button = ttk.Button(discovery, text="Find phones", command=self.find)
        self.find_button.pack(side="left")
        self.choices = ttk.Combobox(discovery, state="readonly", width=24)
        self.choices.pack(side="left", fill="x", expand=True, padx=6)
        self.choices.bind("<<ComboboxSelected>>", self.selected)
        ttk.Label(discovery, text="IP:").pack(side="left")
        ttk.Entry(discovery, textvariable=self.host, width=15).pack(side="left", padx=4)
        buttons = ttk.Frame(self.settings)
        buttons.pack(fill="x", pady=4)
        self.pair_button = ttk.Button(buttons, text="Pair new phone", command=lambda: self.connect(True))
        self.pair_button.pack(side="left")
        self.connect_button = ttk.Button(buttons, text="Reconnect", command=self.startup)
        self.connect_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Disconnect", command=self.disconnect).pack(side="left")
        ttk.Button(buttons, text="Forget phone", command=self.forget).pack(side="right")
        self.confirmation = ttk.LabelFrame(self.settings, text="Verify on the physical phone", padding=6)
        ttk.Label(self.confirmation, textvariable=self.comparison, font=("monospace", 16, "bold")).pack(anchor="w")
        ttk.Label(self.confirmation, text="All four groups must match. Approve on both devices.").pack(anchor="w")
        ttk.Button(self.confirmation, text="Fingerprints match", command=lambda: self.answer(True)).pack(side="left")
        ttk.Button(self.confirmation, text="Reject", command=lambda: self.answer(False)).pack(side="left", padx=6)
        self.separator = ttk.Separator(self.settings)
        self.separator.pack(fill="x", pady=4)
        self.telemetry_panel = ttk.Frame(panel)
        self.telemetry_panel.pack(fill="x")
        for col, (name, title) in enumerate((("gyro", "Gyroscope"), ("accel", "Accelerometer"), ("mag", "Magnetometer"))):
            self.telemetry_panel.columnconfigure(col, weight=1, uniform="sensor")
            box = ttk.LabelFrame(self.telemetry_panel, text=title+" · "+SENSORS[name], padding=4)
            box.grid(row=0, column=col, sticky="nsew", padx=2)
            value = tk.StringVar(value="Not connected")
            self.rows[name] = value
            ttk.Label(box, textvariable=value, font=("monospace", 9), wraplength=200).pack(anchor="w")
        ttk.Label(panel, textvariable=self.geometry, wraplength=660).pack(anchor="w")
        ttk.Label(panel, textvariable=self.health, wraplength=660).pack(anchor="w")
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

    def toggle_connection(self):
        if self.settings.winfo_manager():
            self.settings.pack_forget()
        else:
            self.show_connection()

    def show_connection(self):
        self.settings.pack(fill="x", pady=4, before=self.telemetry_panel)

    def startup(self):
        if self.closed or (self.worker and self.worker.is_alive()):
            return
        try:
            saved = self.store.load()
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            return
        self.auto_hosts = []
        self.auto_error = ""
        self.find(auto=bool(saved))

    def find(self, auto=False):
        if self.searching:
            return
        if self.worker and self.worker.is_alive():
            self.status.set("Disconnect before searching for another phone.")
            return
        self.auto_search = auto
        self.searching = True
        self.find_button.configure(state="disabled")
        self.status.set("Searching for saved phone…" if auto else "Searching the LAN…")
        def search():
            try:
                self.notify("phones", discover())
            except OSError:
                self.notify("phones", [])
        threading.Thread(target=search, daemon=True).start()

    def connect_next(self):
        if self.closed or not self.auto_connecting:
            return
        if self.worker and self.worker.is_alive():
            self.parent.after(50, self.connect_next)
            return
        if not self.auto_hosts:
            self.auto_connecting = False
            self.status.set("Saved phone unavailable. "+(self.auto_error or "Start the phone connection and try Reconnect."))
            return
        self.host.set(self.auto_hosts.pop(0))
        self.connect(automatic=True)

    def selected(self, _event=None):
        index = self.choices.current()
        if 0 <= index < len(self.phones):
            self.host.set(self.phones[index]["host"])

    def connect(self, pair=False, automatic=False):
        if self.worker and self.worker.is_alive():
            self.status.set("Disconnect the current phone before connecting again.")
            return
        if not automatic:
            self.auto_search = False
            self.auto_connecting = False
            self.auto_hosts = []
        if pair:
            self.show_connection()
        self.status.set(("Pairing with " if pair else "Connecting to saved phone at ")+self.host.get().strip()+"…")
        self.link = PhoneLink(self.store, self.notify, self.confirm)
        self.worker = threading.Thread(target=self.link.run, args=(self.host.get().strip(), pair), daemon=True)
        self.worker.start()
        self.pair_button.configure(state="disabled")
        self.connect_button.configure(state="disabled")

    def disconnect(self):
        self.auto_search = False
        self.auto_connecting = False
        self.auto_hosts = []
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
        self.auto_search = False
        self.auto_connecting = False
        self.auto_hosts = []
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
                if kind == "error":
                    self.auto_error = value
            elif kind == "connected":
                self.auto_hosts = []
                self.auto_search = False
                self.auto_connecting = False
                self.auto_error = ""
                self.settings.pack_forget()
            elif kind == "confirm":
                self.approval = value
                self.comparison.set(value["fingerprint"])
                self.show_connection()
                self.confirmation.pack(fill="x", pady=8, before=self.separator)
            elif kind == "phones":
                self.searching, self.phones = False, value
                self.find_button.configure(state="normal")
                self.choices.configure(values=[f"{p['name']} — {p['host']}" + (" (pairing)" if p['pairing'] else "") for p in value])
                if self.worker and self.worker.is_alive():
                    self.auto_search = False
                    continue
                hosts = [phone["host"] for phone in value]
                if value:
                    self.choices.current(hosts.index(self.host.get()) if self.host.get() in hosts else 0)
                    if not self.auto_search:
                        self.selected()
                if self.auto_search:
                    self.auto_search = False
                    try:
                        saved = self.store.load()
                    except (OSError, ValueError) as error:
                        self.status.set(str(error))
                        saved = None
                    if saved:
                        candidates = [self.host.get(), saved.get("host")] + hosts
                        self.auto_hosts = list(dict.fromkeys(h for h in candidates if isinstance(h, str) and h))[:8]
                        self.auto_connecting = True
                        self.connect_next()
                else:
                    self.status.set(f"Found {len(value)} phone(s). Select one to pair."
                                    if value else "No phones found. Start the phone connection or enter its IP.")
            elif kind == "ended":
                self.answer(False)
                if self.forget_pending:
                    self.forget_saved()
                self.pair_button.configure(state="normal")
                self.connect_button.configure(state="normal")
                if self.auto_connecting and not self.forget_pending:
                    self.parent.after(50, self.connect_next)
        snapshot = self.link.snapshot() if self.link else None
        if snapshot:
            self.geometry.set("Phone body / case: %.1f × %.1f mm" % tuple(x * 1000 for x in snapshot["dimensions"][:2]))
            for name, row in snapshot["rows"].items():
                if not row["available"]:
                    text = "Unavailable on this phone"
                elif not row["live"]:
                    text = "Waiting / stale — no fresh samples"
                else:
                    sample = row["sample"]
                    xyz = " ".join(f"{axis} {v:+.3f}" for axis, v in zip("XYZ", sample["v"]))
                    age = "clock syncing" if row["age_ms"] is None else f"age ≈ {row['age_ms']:.1f} ms"
                    text = f"{xyz}\n{row['hz']:.1f} Hz · {age}"
                self.rows[name].set(text)
            rtt = snapshot["rtt_ms"]
            clock = "clock syncing" if rtt is None else f"RTT {rtt:.2f} ms"
            self.health.set(f"{snapshot['count']} samples · {snapshot['gaps']} gaps · {snapshot['dropped']} dropped · {clock}")
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

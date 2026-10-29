"""Phone LAN protocol and diagnostics. Standard-library TLS; no camera privileges."""
from collections import deque
import hashlib
import ipaddress
import json
import math
import os
import queue
from pathlib import Path
import socket
import ssl
import stat
import struct
import tempfile
import threading
import time

PORT = 47643
MAX_MESSAGE = 65536
DISCOVERY = b"FRAMEPHONE_DISCOVER_V1"
SENSORS = {"gyro": "rad/s", "accel": "m/s^2", "mag": "uT"}
PHONE_ERRORS = {
    "pairing_closed": "The phone's pairing window expired. Use Details → Pair using Wi-Fi on the phone, then Pair new phone here.",
    "pairing_rejected_or_expired": "Pairing was rejected or timed out. Reopen pairing and approve matching fingerprints on both screens.",
    "authentication_failed": "The phone rejected the saved pairing. Start new pairing on both devices.",
    "protocol_error": "The phone could not process this connection. Check its connection status and update both apps.",
}


def fingerprint(pin):
    return " ".join(pin[i:i + 4].upper() for i in range(0, 16, 4))


def read_message(sock):
    def exact(size):
        result = bytearray()
        while len(result) < size:
            chunk = sock.recv(size - len(result))
            if not chunk:
                raise ConnectionError("Phone closed the connection")
            result.extend(chunk)
        return result
    size, = struct.unpack("!I", exact(4))
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Invalid phone message size")
    message = json.loads(exact(size))
    if not isinstance(message, dict):
        raise ValueError("Expected a phone message object")
    if not isinstance(message.get("type"), str) or not 1 <= len(message["type"]) <= 64:
        raise ValueError("Invalid phone message type")
    if message.get("type") == "error":
        code = message.get("code")
        raise ValueError(PHONE_ERRORS.get(code if isinstance(code, str) else None,
                                         "Phone reported a connection error. Check the phone's status."))
    return message


def write_message(sock, message):
    data = json.dumps(message, allow_nan=False, separators=(",", ":")).encode()
    if not 0 < len(data) <= MAX_MESSAGE:
        raise ValueError("Invalid message size")
    sock.sendall(struct.pack("!I", len(data)) + data)


def hex_string(value, size=64):
    return isinstance(value, str) and len(value) == size and all(c in "0123456789abcdef" for c in value)


def pairing_fingerprint(pin, client_nonce, phone_nonce):
    if not all(hex_string(value) for value in (pin, client_nonce, phone_nonce)):
        raise ValueError("Invalid pairing nonce")
    return fingerprint(hashlib.sha256((pin + client_nonce + phone_nonce).encode("ascii")).hexdigest())


class PairingStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Pairing file must be owned by you and private (mode 0600)")
        if info.st_size > 4096:
            raise ValueError("Invalid pairing file")
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or not hex_string(data.get("pin")) or not hex_string(data.get("credential")):
            raise ValueError("Invalid saved pairing; forget it and pair again")
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".phone-pairing-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(data, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def forget(self):
        self.path.unlink(missing_ok=True)


def discover(timeout=3.0, targets=None):
    """Untrusted endpoint hints. Auth never uses a discovery-supplied identity."""
    found = {}
    destinations = set(targets or ["255.255.255.255"])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.bind(("", 0))
        udp.settimeout(0.2)
        if targets is None:
            # Directed broadcasts also work on hosts with more than one NIC.
            import fcntl
            for _, interface in socket.if_nameindex():
                try:
                    info = fcntl.ioctl(udp, 0x8919, struct.pack("256s", interface.encode()[:15]))
                    destinations.add(socket.inet_ntoa(info[20:24]))
                except OSError:
                    pass
        end, next_send = time.monotonic() + timeout, 0
        while time.monotonic() < end:
            if time.monotonic() >= next_send:
                for address in destinations:
                    try:
                        udp.sendto(DISCOVERY, (address, PORT))
                    except OSError:
                        pass
                next_send = time.monotonic() + 1
            try:
                raw, (host, _) = udp.recvfrom(2048)
                message = json.loads(raw)
                if (isinstance(message, dict) and message.get("service") == "framephone"
                        and message.get("version") == 1 and message.get("port") == PORT):
                    name = str(message.get("name", "Phone"))[:60]
                    found[host] = {"host": host, "name": "".join(c for c in name if c.isprintable()),
                                   "pairing": message.get("pairing") is True}
            except (socket.timeout, ValueError, UnicodeError):
                continue
    return list(found.values())


def integer(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("Invalid integer telemetry field")
    return value


def vector(value):
    if (not isinstance(value, list) or len(value) != 3
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)):
        raise ValueError("Invalid sensor vector")
    return value


def validate_fiducial(value):
    if value is None:
        return None  # Older phones may still send telemetry, but cannot start tracking.
    if not isinstance(value, dict):
        raise ValueError("Invalid fiducial profile")
    edge = value.get("black_edge_m")
    if (value.get("family") != "tag36h11" or type(value.get("id")) is not int or value["id"] != 0
            or type(edge) not in (float, int) or not math.isfinite(edge) or not .01 <= edge <= .2
            or value.get("origin") != "black_square_center" or value.get("axes") != "right_up_front"
            or value.get("size_source") not in ("manual_black_edge", "android_display_dpi")):
        raise ValueError("Invalid fiducial profile; check the phone's reported marker geometry")
    result = {key: value[key] for key in ("family", "id", "black_edge_m", "origin", "axes", "size_source")}
    layout = ("screen_width_px", "screen_height_px", "black_edge_px")
    if any(key in value for key in layout):
        if not all(type(value.get(key)) is int for key in layout):
            raise ValueError("Invalid marker screen geometry")
        width, height, black = (value[key] for key in layout)
        if not 100 <= width <= height <= 10000 or black != min(width, height)//10*8:
            raise ValueError("Invalid fullscreen marker layout")
        result.update({key: value[key] for key in layout})
    return result


class Telemetry:
    """Bounded diagnostic state, independent from Tk and the optical tracker."""
    def __init__(self, profile):
        if profile.get("type") != "profile" or profile.get("version") != 1:
            raise ValueError("Unsupported phone profile")
        if profile.get("clock") != "android_elapsed_realtime_ns" or profile.get("axes") != "android_natural_device":
            raise ValueError("Unsupported sensor coordinates/clock")
        self.session = profile.get("session")
        if not isinstance(self.session, str) or not 1 <= len(self.session) <= 64:
            raise ValueError("Invalid session")
        dimensions = profile["dimensions"]
        w, h = (dimensions[key] for key in ("width_m", "height_m"))
        if not all(type(x) in (int, float) and math.isfinite(x) for x in (w, h)):
            raise ValueError("Invalid dimensions")
        if not .02 <= w <= .5 or not w <= h <= .8:
            raise ValueError("Invalid dimensions")
        self.dimensions = (w, h)
        self.automatic_marker = profile.get("automatic_marker_v1") is True
        self.fiducial = validate_fiducial(profile.get("fiducial"))
        self.marker_displayed = None
        self.marker_state_ns = None
        self.capabilities = {}
        for capability in profile["sensors"]:
            name = capability["sensor"]
            if name not in SENSORS or name in self.capabilities:
                raise ValueError("Invalid sensor capabilities")
            if capability.get("available") and capability.get("units") != SENSORS[name]:
                raise ValueError("Unexpected sensor units")
            self.capabilities[name] = capability
        self.samples, self.times, self.arrivals = {}, {}, {}
        self.gaps, self.count, self.dropped = 0, 0, 0
        self.probes = deque(maxlen=30)
        self.offset_ns, self.rtt_ns = None, None
        self.arcore_enabled = profile.get("arcore_pose_v1") is True
        self.arcore_poses = deque(maxlen=90)
        self.arcore_received_ns = 0
        self.gyro_history = deque(maxlen=96)

    def clock_reply(self, message, h3, pending):
        h0, p1, p2 = (integer(message[k]) for k in ("h0", "p1", "p2"))
        if message.get("session") != self.session or h0 not in pending:
            raise ValueError("Unexpected clock reply")
        pending.remove(h0)
        rtt = (h3 - h0) - (p2 - p1)
        if p2 < p1 or not 0 <= rtt <= 2_000_000_000:
            raise ValueError("Invalid clock exchange")
        offset = ((p1 - h0) + (p2 - h3)) / 2
        # Sleep/resume can change the relation between these two monotonic clocks.
        # Discard old diagnostic offsets rather than displaying an obsolete age.
        if self.offset_ns is not None and abs(offset - self.offset_ns) > 50_000_000:
            self.probes.clear()
            self.arcore_poses.clear()
            self.gyro_history.clear()
        self.probes.append((h3, rtt, offset))
        recent = [p for p in self.probes if h3 - p[0] <= 10_000_000_000]
        _, self.rtt_ns, self.offset_ns = min(recent, key=lambda p: p[1])

    def receive(self, message, now, gyro_for_prediction=True):
        if message.get("type") == "arcore_pose":
            if not self.arcore_enabled or message.get("session") != self.session:
                raise ValueError("Unannounced ARCore pose/session")
            for key in ("generation", "acquisition"):
                value = message.get(key)
                if not isinstance(value, str) or not 1 <= len(value) <= 64 or not value.isascii() or not value.isprintable():
                    raise ValueError("Invalid ARCore identity")
            seq, stamp = integer(message.get("seq")), integer(message.get("t_ns"))
            integer(message.get("frame_timestamp_ns"))
            reason = message.get("reason", "")
            if not isinstance(reason, str) or len(reason) > 120:
                raise ValueError("Invalid ARCore tracking reason")
            if (seq == 0 or stamp == 0 or message.get("state") not in ("tracking", "paused", "error", "stopped") or
                    type(message.get("marker_required")) is not bool or message.get("transform") != "T_AD" or
                    message.get("time_source") != "update_elapsed_realtime_ns"):
                raise ValueError("Invalid ARCore state/coordinates")
            if self.arcore_poses:
                previous = self.arcore_poses[-1]
                if previous["generation"] == message["generation"]:
                    if seq <= previous["seq"] or stamp <= previous["t_ns"]:
                        raise ValueError("Reordered ARCore pose")
                else:
                    self.arcore_poses.clear()
            keys = ("generation", "acquisition", "seq", "t_ns", "frame_timestamp_ns", "state", "marker_required")
            pose = {key: message[key] for key in keys}
            pose["reason"] = reason
            if "capture_t_ns" in message:
                capture = integer(message["capture_t_ns"])
                if (message.get("capture_time_source") != "camera2_realtime_center_exposure" or
                        not 0 <= stamp-capture <= 200_000_000):
                    raise ValueError("Invalid ARCore capture clock")
                pose["capture_t_ns"] = capture
            if message["state"] == "tracking":
                translation = vector(message.get("translation_m"))
                rotation = message.get("quaternion_xyzw")
                if (not isinstance(rotation, list) or len(rotation) != 4 or
                        any(type(x) not in (int, float) or not math.isfinite(x) for x in rotation) or
                        abs(sum(x*x for x in rotation)-1) > .002 or
                        any(abs(x) > 10000 for x in translation)):
                    raise ValueError("Invalid ARCore transform")
                pose.update(translation_m=list(translation), quaternion_xyzw=list(rotation))
            self.arcore_poses.append(pose)
            self.arcore_received_ns = now
            return
        if message.get("type") == "marker_state":
            if message.get("session") != self.session or type(message.get("displayed")) is not bool:
                raise ValueError("Invalid marker state/session")
            target = validate_fiducial(message.get("fiducial"))
            if target is None and message["displayed"]:
                raise ValueError("Displayed marker has no valid geometry")
            self.fiducial = target
            self.marker_displayed = message["displayed"]
            self.marker_state_ns = now
            return
        if message.get("type") != "samples" or message.get("session") != self.session:
            raise ValueError("Unexpected telemetry session/message")
        samples = message["samples"]
        if not isinstance(samples, list) or len(samples) > 64:
            raise ValueError("Oversized sensor batch")
        dropped = integer(message["dropped"])
        if dropped < self.dropped:
            raise ValueError("Reversed sensor drop counter")
        self.dropped = dropped
        for sample in samples:
            name = sample["sensor"]
            if name not in self.capabilities or not self.capabilities[name].get("available"):
                raise ValueError("Unannounced sensor")
            sequence, timestamp = integer(sample["seq"]), integer(sample["t_ns"])
            if sequence == 0:
                raise ValueError("Sensor sequences start at one")
            vector(sample["v"])
            if "bias" in sample:
                vector(sample["bias"])
            if type(sample.get("accuracy")) is not int or not -1 <= sample["accuracy"] <= 3:
                raise ValueError("Invalid sensor accuracy")
            previous = self.samples.get(name)
            if previous and (sequence <= previous["seq"] or timestamp <= previous["t_ns"]):
                raise ValueError("Reordered sensor samples")
            self.gaps += sequence - (previous["seq"] if previous else 0) - 1
            self.samples[name] = sample
            times = self.times.setdefault(name, deque(maxlen=512))
            times.append(timestamp)
            while len(times) > 1 and timestamp - times[0] > 2_000_000_000:
                times.popleft()
            self.arrivals[name] = now
            if name == "gyro" and gyro_for_prediction:
                cap = self.capabilities[name]
                if not cap.get("uncalibrated") or "bias" in sample:
                    bias = sample.get("bias", [0, 0, 0]) if cap.get("uncalibrated") else [0, 0, 0]
                    w = [a-b for a, b in zip(sample["v"], bias)]
                    if all(math.isfinite(x) for x in w) and math.hypot(*w) <= 35:
                        self.gyro_history.append({"t_ns": timestamp, "w_rad_s": w})
            self.count += 1

    def pose_packet(self, now, compact=False):
        if not self.arcore_enabled:
            return None
        poses = list(self.arcore_poses)
        if compact and poses:
            if poses[-1]["state"] != "tracking":
                poses = poses[-1:]
            elif not poses[-1]["marker_required"]:
                poses = poses[-6:]
        mapped = []
        if self.offset_ns is not None:
            for sample in poses:
                value = dict(sample, host_t_ns=round(sample["t_ns"]-self.offset_ns))
                value["pose_host_t_ns"] = round(sample.get("capture_t_ns", sample["t_ns"])-self.offset_ns)
                mapped.append(value)
        latest = self.arcore_poses[-1] if self.arcore_poses else None
        recent = [p for p in self.arcore_poses if p["state"] == "tracking" and
                  p["generation"] == latest["generation"] and p["acquisition"] == latest["acquisition"]]
        span = recent[-1]["t_ns"]-recent[0]["t_ns"] if len(recent)>1 else 0
        return {"schema": "framephone-arcore-v1", "session": self.session,
                "clock_valid": bool(self.probes and 0 <= now-self.probes[-1][0] <= 10_000_000_000
                                    and self.rtt_ns <= 40_000_000),
                "received_host_monotonic_ns": self.arcore_received_ns,
                "pose_hz": (len(recent)-1)*1e9/span if span else 0,
                "source_hz": (recent[-1]["seq"]-recent[0]["seq"])*1e9/span if span else 0,
                "poses": mapped,
                "gyro": [dict(host_t_ns=round(p["t_ns"]-self.offset_ns), w_rad_s=list(p["w_rad_s"]))
                         for p in list(self.gyro_history)[-64:]]
                        if (self.offset_ns is not None and latest and latest["state"] == "tracking"
                            and not latest["marker_required"] and "capture_t_ns" in latest) else []}

    def snapshot(self, now):
        rows = {}
        for name in SENSORS:
            cap = self.capabilities.get(name, {})
            sample, times = self.samples.get(name), self.times.get(name, [])
            live = sample is not None and now - self.arrivals[name] < 1_000_000_000
            rows[name] = {"available": bool(cap.get("available")), "sample": sample, "live": live,
                          "uncalibrated": cap.get("uncalibrated", False),
                          "hz": (len(times) - 1) * 1e9 / (times[-1] - times[0]) if live and len(times) > 1 else 0,
                          "age_ms": (now + self.offset_ns - sample["t_ns"]) / 1e6
                          if live and self.offset_ns is not None else None}
        return {"rows": rows, "count": self.count, "gaps": self.gaps, "dropped": self.dropped,
                "session": self.session, "dimensions": self.dimensions, "fiducial": self.fiducial,
                "automatic_marker": self.automatic_marker,
                "marker_displayed": self.marker_displayed,
                "marker_state_fresh": self.marker_state_ns is not None and now-self.marker_state_ns < 1_000_000_000,
                "arcore": self.pose_packet(now),
                "rtt_ms": None if self.rtt_ns is None else self.rtt_ns / 1e6}


class PhoneLink:
    def __init__(self, store, notify, confirm, bluetooth=None):
        self.store, self.notify, self.confirm = store, notify, confirm
        self.stopped = threading.Event()
        self.sock = None
        self.lock = threading.Lock()
        self.telemetry = None
        self.profile = None
        self.profile_received_ns = None
        self.recording = None
        self.commands = queue.Queue(maxsize=8)
        self.retryable = False
        self.headset = (False, 0)
        self.bluetooth = bluetooth
        self.ble_telemetry = None
        self.bluetooth_only = False
        self.clock_pending = set()
        self.next_clock = self.next_presence = 0
        self.pump_thread = None
        self.pump_lock = threading.Lock()

    def start_bluetooth(self, profile):
        state = Telemetry(profile)
        with self.lock:
            self.telemetry = self.ble_telemetry = state
            self.profile = profile
            self.profile_received_ns = time.monotonic_ns()
            self.bluetooth_only = True
        self.bluetooth.authorize(state.session, self.receive_bluetooth)
        self.pump_thread = threading.Thread(target=self._pump_bluetooth, name='bluetooth-tracking', daemon=True)
        self.pump_thread.start()

    def _pump_bluetooth(self):
        while not self.stopped.wait(.05):
            self.pump_bluetooth()

    def pump_bluetooth(self):
        with self.pump_lock:
            self._send_bluetooth_updates()

    def _send_bluetooth_updates(self):
        if not self.bluetooth_only or self.stopped.is_set():
            return
        now = time.monotonic_ns()
        presence = self.presence_message(now)
        if presence and now >= self.next_presence and self.bluetooth.send_tracking(presence):
            self.next_presence = now+500_000_000
        if now >= self.next_clock:
            with self.lock:
                self.clock_pending.clear()
                self.clock_pending.add(now)
                session = self.telemetry.session
            if self.bluetooth.send_tracking(dict(type='ping', session=session, h0=now)):
                self.next_clock = now+2_000_000_000
            else:
                with self.lock:
                    self.clock_pending.discard(now)
        for _ in range(8):
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            if not self.bluetooth.send_tracking(command):
                try: self.commands.put_nowait(command)
                except queue.Full: pass
                break

    def headset_presence(self, worn, updated_host_ns):
        """Latest-only wearer state. A frozen UI/monitor cannot renew its timestamp."""
        with self.lock:
            self.headset = (bool(worn), updated_host_ns)

    def presence_message(self, now):
        with self.lock:
            if not self.profile or not self.profile.get("headset_presence_v1") or not self.telemetry:
                return None
            worn, stamp = self.headset
            return {"type": "headset_presence", "session": self.telemetry.session,
                    "worn": worn and 0 <= now-stamp <= 1_000_000_000}

    def alignment_command(self, kind, generation, acquisition):
        if kind not in ("alignment_accepted", "alignment_lost"):
            raise ValueError("Invalid alignment command")
        with self.lock:
            if not self.telemetry or not self.telemetry.arcore_enabled:
                return False
            message = {"type": kind, "session": self.telemetry.session,
                       "generation": generation, "acquisition": acquisition}
        try:
            self.commands.put_nowait(message)
            return True
        except queue.Full:
            return False

    def receive_bluetooth(self, message, gyro, now):
        with self.lock:
            state = self.ble_telemetry
            if self.stopped.is_set() or state is None:
                return
            try:
                if message.get('type') == 'pong' and self.bluetooth_only:
                    state.clock_reply(message, now, self.clock_pending)
                elif message.get('type') == 'gyro_samples':
                    if (message.get('session') != state.session or not state.arcore_poses or
                            not 0 <= now-state.arcore_received_ns <= 150_000_000):
                        return
                    latest = state.arcore_poses[-1]
                    if (latest['state'] != 'tracking' or latest['marker_required'] or
                            any(message.get(k) != latest[k] for k in ('generation', 'acquisition'))):
                        return
                    gyro = [sample for sample in gyro if -200_000_000 <= sample['t_ns']-latest['t_ns'] <= 250_000_000]
                else:
                    state.receive(message, now, gyro_for_prediction=not self.bluetooth_only)
                for sample in gyro:
                    if not state.gyro_history or sample['t_ns'] > state.gyro_history[-1]['t_ns']:
                        state.gyro_history.append(sample)
                if self.recording and message.get('type') != 'gyro_samples':
                    self.recording.submit(message, now, transport='bluetooth')
            except (ValueError, KeyError, TypeError):
                return  # Old/reordered Bluetooth traffic never ends the TLS session.

    def _pose_state(self, now):
        ble = self.ble_telemetry
        if (ble and ble.arcore_poses and 0 <= now-ble.arcore_received_ns <= 150_000_000 and
                (not self.telemetry.arcore_poses or
                 ble.arcore_poses[-1]['t_ns'] >= self.telemetry.arcore_poses[-1]['t_ns'])):
            # The same phone monotonic clock applies to both radios; clock
            # probes remain on reliable TLS. Never replace sample timestamps.
            ble.offset_ns = self.telemetry.offset_ns
            ble.probes = self.telemetry.probes.copy()
            ble.rtt_ns = self.telemetry.rtt_ns
            return ble
        return self.telemetry

    def start_recording(self, path):
        from telemetry_recording import TelemetryRecording
        with self.lock:
            if self.telemetry is None or self.stopped.is_set():
                raise ValueError("Connect the phone before recording telemetry")
            if self.recording is not None:
                raise ValueError("A telemetry recording is already active")
            self.recording = TelemetryRecording(path, self.profile, self.profile_received_ns)
            return self.recording

    def stop_recording(self):
        with self.lock:
            recording, self.recording = self.recording, None
        if recording:
            recording.close()

    def stop(self):
        self.stopped.set()
        if self.bluetooth_only and self.bluetooth and self.telemetry:
            self.bluetooth.revoke(self.telemetry.session)
            self.stop_recording()
            if self.pump_thread and self.pump_thread is not threading.current_thread():
                self.pump_thread.join(timeout=1)
        sock = self.sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def snapshot(self):
        with self.lock:
            if not self.telemetry:
                return None
            now = time.monotonic_ns()
            result = self.telemetry.snapshot(now)
            state = self._pose_state(now)
            result['arcore'] = state.pose_packet(now)
            result['pose_transport'] = 'bluetooth' if state is self.ble_telemetry else 'wifi'
            return result

    def pose_packet(self):
        with self.lock:
            now = time.monotonic_ns()
            return self._pose_state(now).pose_packet(now, compact=True) if self.telemetry else None

    def run(self, host, pair=False, port=PORT):
        phase = "connection setup"
        try:
            ipaddress.IPv4Address(host)
            saved = None if pair else self.store.load()
            if not pair and not saved:
                raise ValueError("No saved phone. Start pairing on the phone, then choose Pair new phone.")
            self.notify("status", "Connecting…")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            # First enrollment is authenticated by physical fingerprint comparison.
            # Reconnect checks the full persisted pin before sending any credential.
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=5) as raw:
                self.sock = raw
                phase = "TLS handshake"
                with context.wrap_socket(raw, server_hostname=None) as sock:
                    self.sock = sock
                    if self.stopped.is_set():
                        return
                    phase = "pairing request" if pair else "reconnect authentication"
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    pin = hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest()
                    if saved and pin != saved["pin"]:
                        raise ValueError("Phone identity changed. No credential sent. Verify the phone and pair again.")
                    hello = {"type": "hello", "version": 1, "mode": "pair" if pair else "reconnect",
                             "marker_state_v1": True,
                             "arcore_pose_v1": True,
                             "name": socket.gethostname()[:60]}
                    if saved:
                        hello["credential"] = saved["credential"]
                    else:
                        hello["nonce"] = os.urandom(32).hex()
                    write_message(sock, hello)
                    if pair:
                        message = read_message(sock)
                        if message.get("type") != "pairing":
                            raise ValueError("Phone is not accepting pairing")
                        accepted = self.confirm(pairing_fingerprint(pin, hello["nonce"], message.get("nonce")), self.stopped)
                        if not accepted or self.stopped.is_set():
                            raise ValueError("Pairing cancelled; no phone saved")
                        write_message(sock, {"type": "confirm", "accepted": True})
                        phase = "pairing approval"
                        self.notify("status", "Approve the matching fingerprint on the phone…")
                        sock.settimeout(65)
                        message = read_message(sock)
                        if message.get("type") != "paired" or not hex_string(message.get("credential")):
                            raise ValueError("Phone did not approve pairing")
                        saved = {"pin": pin, "credential": message["credential"], "host": host}
                        self.store.save(saved)
                    sock.settimeout(4)
                    phase = "sensor startup"
                    profile = read_message(sock)
                    profile_received_ns = time.monotonic_ns()
                    telemetry = Telemetry(profile)
                    with self.lock:
                        self.telemetry = telemetry
                        self.profile = profile
                        self.profile_received_ns = profile_received_ns
                        if self.bluetooth and profile.get('bluetooth_pose_v1') is True:
                            self.ble_telemetry = Telemetry(profile)
                    if self.ble_telemetry:
                        self.bluetooth.authorize(telemetry.session, self.receive_bluetooth)
                    if saved.get("host") != host:
                        saved["host"] = host
                        self.store.save(saved)
                    self.notify("connected", host)
                    self.notify("status", "Connected — receiving phone sensors")
                    phase = "sensor streaming"
                    pending, next_ping = set(), 0
                    presence_at, previous_presence = 0, None
                    while not self.stopped.is_set():
                        for _ in range(8):
                            try:
                                command = self.commands.get_nowait()
                            except queue.Empty:
                                break
                            write_message(sock, command)
                        now = time.monotonic_ns()
                        presence = self.presence_message(now)
                        if presence is not None and (presence != previous_presence or now-presence_at >= 500_000_000):
                            write_message(sock, presence)
                            previous_presence, presence_at = presence, now
                        if now >= next_ping:
                            if pending:
                                raise ConnectionError("Phone clock/heartbeat reply timed out")
                            pending.add(now)
                            write_message(sock, {"type": "ping", "h0": now})
                            next_ping = now + 2_000_000_000
                        message = read_message(sock)
                        now = time.monotonic_ns()
                        with self.lock:
                            if message.get("type") == "pong":
                                previous_offset = telemetry.offset_ns
                                telemetry.clock_reply(message, now, pending)
                                if (self.ble_telemetry and previous_offset is not None and
                                        abs(telemetry.offset_ns-previous_offset) > 50_000_000):
                                    self.ble_telemetry.arcore_poses.clear()
                                    self.ble_telemetry.gyro_history.clear()
                            else:
                                telemetry.receive(message, now)
                            if self.recording:
                                self.recording.submit(message, now, transport='wifi')
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            self.retryable = not self.stopped.is_set() and (
                (isinstance(error, OSError) and not isinstance(error, ssl.SSLError)) or isinstance(error, ssl.SSLEOFError))
            if not self.stopped.is_set():
                # Never include arbitrary peer-controlled messages or credentials in logs.
                if isinstance(error, ssl.SSLError):
                    self.notify("error", f"Secure connection failed during {phase}. "
                                "Install the updated phone APK and check the phone's TLS status. "
                                f"Details: {error}")
                else:
                    self.notify("error", str(error) if isinstance(error, (OSError, ValueError)) else "Malformed phone telemetry")
        finally:
            if self.bluetooth and self.telemetry:
                self.bluetooth.revoke(self.telemetry.session)
            self.sock = None
            with self.lock:
                self.telemetry = None
                self.ble_telemetry = None
                self.profile = None
                self.profile_received_ns = None
            self.stop_recording()
            self.notify("ended", "Disconnected")

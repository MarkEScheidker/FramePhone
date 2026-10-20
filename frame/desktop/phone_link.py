"""Phone LAN protocol and diagnostics. Standard-library TLS; no camera privileges."""
from collections import deque
from photo_reference import PhotoReceiver
import hashlib
import ipaddress
import json
import math
import os
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
    "pairing_closed": "The phone's pairing window expired. Tap Pair new headset on the phone, then Pair new phone here.",
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
    return {key: value[key] for key in ("family", "id", "black_edge_m", "origin", "axes", "size_source")}


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
        w, h, d = (dimensions[key] for key in ("width_m", "height_m", "thickness_m"))
        if not all(type(x) in (int, float) and math.isfinite(x) for x in (w, h, d)):
            raise ValueError("Invalid dimensions")
        if not .02 <= w <= .5 or not w <= h <= .8 or not .001 <= d <= .1:
            raise ValueError("Invalid dimensions")
        self.dimensions = (w, h, d)
        self.fiducial = validate_fiducial(profile.get("fiducial"))
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
        self.probes.append((h3, rtt, offset))
        recent = [p for p in self.probes if h3 - p[0] <= 10_000_000_000]
        _, self.rtt_ns, self.offset_ns = min(recent, key=lambda p: p[1])

    def receive(self, message, now):
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
            self.count += 1

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
                "rtt_ms": None if self.rtt_ns is None else self.rtt_ns / 1e6}


class PhoneLink:
    def __init__(self, store, notify, confirm):
        self.store, self.notify, self.confirm = store, notify, confirm
        self.stopped = threading.Event()
        self.sock = None
        self.lock = threading.Lock()
        self.telemetry = None
        self.profile = None
        self.profile_received_ns = None
        self.recording = None
        self.photo = PhotoReceiver()
        self.outbound = deque(maxlen=4)

    def request_photo(self):
        with self.lock:
            if self.telemetry is None or self.stopped.is_set() or not self.profile.get("photo_reference_v1"):
                raise ValueError("Connect a phone with the updated photo-test APK first.")
            if len(self.outbound) >= 4:
                raise ValueError("Phone command queue is full")
            self.outbound.append(self.photo.begin_request())

    def photo_reference(self):
        with self.lock:
            return self.photo.data, dict(self.photo.metadata) if self.photo.metadata else None

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
            result = self.telemetry.snapshot(time.monotonic_ns())
            result["photo"] = self.photo.snapshot()
            return result

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
                             "photo_reference_v1": True,
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
                    if saved.get("host") != host:
                        saved["host"] = host
                        self.store.save(saved)
                    self.notify("status", "Connected — receiving phone sensors")
                    phase = "sensor streaming"
                    pending, next_ping = set(), 0
                    while not self.stopped.is_set():
                        with self.lock:
                            commands = list(self.outbound)
                            self.outbound.clear()
                            if self.photo.request and time.monotonic() - self.photo.started > 15:
                                raise ConnectionError("Phone photo transfer timed out; reconnect and retry.")
                        for command in commands:
                            write_message(sock, command)
                        now = time.monotonic_ns()
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
                                telemetry.clock_reply(message, now, pending)
                            elif message.get("type", "").startswith("photo_"):
                                if message.get("session") != telemetry.session:
                                    raise ValueError("Unexpected photo session")
                                self.photo.receive(message)
                            else:
                                telemetry.receive(message, now)
                            if self.recording and not message.get("type", "").startswith("photo_"):
                                self.recording.submit(message, now)
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            if not self.stopped.is_set():
                # Never include arbitrary peer-controlled messages or credentials in logs.
                if isinstance(error, ssl.SSLError):
                    self.notify("error", f"Secure connection failed during {phase}. "
                                "Install the updated phone APK and check the phone's TLS status. "
                                f"Details: {error}")
                else:
                    self.notify("error", str(error) if isinstance(error, (OSError, ValueError)) else "Malformed phone telemetry")
        finally:
            self.sock = None
            with self.lock:
                self.telemetry = None
                self.profile = None
                self.profile_received_ns = None
                self.photo = PhotoReceiver()
                self.outbound.clear()
            self.stop_recording()
            self.notify("ended", "Disconnected")

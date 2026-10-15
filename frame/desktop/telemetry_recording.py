"""Opt-in raw sensor evidence. Disk I/O never runs on the TLS receive thread."""
import json
import queue
import threading


def evidence_message(message):
    """Copy only the published sensor/clock fields, never unknown extensions."""
    def select(value, keys):
        return {key: value[key] for key in keys if key in value}
    kind = message["type"]
    if kind == "profile":
        result = select(message, ("type", "version", "session", "clock", "axes"))
        result["dimensions"] = select(message["dimensions"], ("width_m", "height_m", "thickness_m", "boundary"))
        result["sensors"] = [select(sensor, ("sensor", "available", "units", "uncalibrated", "requested_hz"))
                             for sensor in message["sensors"]]
    elif kind == "samples":
        result = select(message, ("type", "session", "dropped"))
        result["samples"] = [select(sample, ("sensor", "seq", "t_ns", "accuracy", "v", "bias"))
                             for sample in message["samples"]]
    elif kind == "pong":
        result = select(message, ("type", "session", "h0", "p1", "p2"))
    else:
        raise ValueError("Only validated sensor and clock evidence may be recorded")
    return result


class TelemetryRecording:
    def __init__(self, path, profile, host_time_ns):
        self.queue = queue.Queue(maxsize=512)
        self.closed = threading.Event()
        self.error = None
        self.dropped = 0
        self.file = path.open("x", encoding="utf-8")
        self.submit(profile, host_time_ns)
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def submit(self, message, host_time_ns):
        if self.closed.is_set():
            return
        # Caller supplies only validated profile/samples/pong; no enrollment
        # credentials, TLS material, IP address, or arbitrary peer messages.
        item = {"schema": "framephone-telemetry-record-v1",
                "received_host_monotonic_ns": host_time_ns, "message": evidence_message(message)}
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def close(self):
        self.closed.set()
        self.thread.join(timeout=1)

    def _write(self):
        size = 0
        try:
            with self.file:
                while not self.closed.is_set() or not self.queue.empty():
                    try:
                        item = self.queue.get(timeout=.1)
                    except queue.Empty:
                        continue
                    line = json.dumps(item, separators=(",", ":"), allow_nan=False) + "\n"
                    size += len(line.encode("utf-8"))
                    if size > 32 * 1024 * 1024:
                        raise ValueError("32 MiB telemetry recording limit reached")
                    self.file.write(line)
                self.file.write(json.dumps({"schema": "framephone-telemetry-record-v1",
                                           "end": True, "recorder_dropped_messages": self.dropped}) + "\n")
        except (OSError, ValueError) as error:
            self.error = str(error)
            self.closed.set()

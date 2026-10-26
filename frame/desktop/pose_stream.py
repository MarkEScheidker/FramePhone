"""Latest-only renderer publication, independent of Tk and optical diagnostics."""
import json
import threading
import time


class PoseStream:
    def __init__(self, path, source, session, hz=90):
        self.path, self.source, self.session = path, source, session
        self.interval = 1 / hz
        self.stopped = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, name="renderer-poses", daemon=True)
        self.thread.start()

    def _write(self, packet):
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(packet, allow_nan=False, separators=(",", ":")) + "\n")
        temporary.replace(self.path)

    def _lost(self):
        return {"schema": "framephone-arcore-v1", "session": self.session,
                "clock_valid": False, "poses": []}

    def _run(self):
        previous = None
        try:
            while not self.stopped.is_set():
                started = time.monotonic()
                packet = self.source() or self._lost()
                # A bounded source returns copied, validated state. Unchanged
                # data never acquires a new receive/capture timestamp here.
                if packet != previous:
                    self._write(packet)
                    previous = packet
                self.stopped.wait(max(0, self.interval-(time.monotonic()-started)))
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.error = str(error)
        finally:
            try:
                self._write(self._lost())
            except OSError as error:
                self.error = str(error)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)

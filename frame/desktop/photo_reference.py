"""One bounded, authenticated photo transfer; no continuous screen capture."""
import base64
import hashlib
import io
import json
from pathlib import Path
import struct
import time
import uuid

MAX_PHOTO = 2 * 1024 * 1024


class PhotoReceiver:
    def __init__(self):
        self.request = None
        self.data = None
        self.metadata = None
        self.state = {"id": "", "displayed": False}
        self.error = ""
        self.buffer = bytearray()
        self.expected = None
        self.started = 0
        self.state_at = 0

    def begin_request(self):
        if self.request:
            raise ValueError("A photo download is already in progress")
        self.request = uuid.uuid4().hex
        self.data = self.metadata = self.expected = None
        self.error = ""
        self.buffer.clear()
        self.started = time.monotonic()
        return {"type": "request_photo", "request": self.request}

    def receive(self, message):
        kind = message["type"]
        if kind == "photo_state":
            identity = message.get("id")
            if (not isinstance(identity, str) or
                    (identity != "" and (len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity))) or
                    type(message.get("displayed")) is not bool):
                raise ValueError("Invalid photo display state")
            self.state = {"id": identity, "displayed": message["displayed"]}
            self.state_at = time.monotonic()
            return
        if not self.request or message.get("request") != self.request:
            raise ValueError("Unexpected photo transfer")
        if kind == "photo_missing":
            self.request = None
            self.error = "Choose a tracking photo on the phone first."
        elif kind == "photo_begin":
            size, width, height = (message.get(k) for k in ("size", "width", "height"))
            identity = message.get("id")
            if (self.expected is not None or any(type(n) is not int for n in (size, width, height)) or
                    not 0 < size <= MAX_PHOTO or not 64 <= width <= 960 or not 64 <= height <= 960 or
                    not .2 <= height / width <= 5 or not isinstance(identity, str) or len(identity) != 64 or
                    any(c not in "0123456789abcdef" for c in identity)):
                raise ValueError("Invalid photo reference metadata")
            self.expected = {"id": identity, "size": size, "width": width, "height": height}
        elif kind == "photo_chunk":
            encoded = message.get("data")
            if (not self.expected or type(message.get("offset")) is not int or
                    message["offset"] != len(self.buffer) or not isinstance(encoded, str) or len(encoded) > 22000):
                raise ValueError("Invalid photo chunk")
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise ValueError("Invalid photo encoding") from None
            if not 0 < len(data) <= 16384 or len(self.buffer) + len(data) > self.expected["size"]:
                raise ValueError("Photo transfer exceeds its declared size")
            self.buffer.extend(data)
        elif kind == "photo_end":
            if not self.expected or len(self.buffer) != self.expected["size"]:
                raise ValueError("Incomplete photo reference")
            data = bytes(self.buffer)
            if (hashlib.sha256(data).hexdigest() != self.expected["id"] or len(data) < 24 or
                    data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" or
                    struct.unpack("!II", data[16:24]) != (self.expected["width"], self.expected["height"])):
                raise ValueError("Photo hash, format or dimensions mismatch")
            self.data, self.metadata = data, dict(self.expected)
            self.request = self.expected = None
            self.buffer.clear()
        else:
            raise ValueError("Unexpected photo message")

    def snapshot(self):
        state = dict(self.state)
        if time.monotonic() - self.state_at > 1.5:
            state["displayed"] = False
        return {"metadata": dict(self.metadata) if self.metadata else None, "state": state,
                "downloading": self.request is not None, "error": self.error}


def create_session(directory, factory_root, selections, ring, photo, metadata, phone_session, record=False, backend="rootsift"):
    from PIL import Image
    left, right, left_stream, right_stream = selections
    if not all(selections) or left == right or left_stream == right_stream:
        raise ValueError("Choose two distinct front streams and their factory calibrations.")
    if backend not in ("rootsift", "xfeat"):
        raise ValueError("Unknown photo matcher")
    if not photo or len(photo) > MAX_PHOTO or hashlib.sha256(photo).hexdigest() != metadata["id"]:
        raise ValueError("Download the phone photo before starting tracking.")
    with Image.open(io.BytesIO(photo)) as source:
        if source.format != "PNG" or source.size != (metadata["width"], metadata["height"]):
            raise ValueError("Reference image format/dimensions mismatch")
        if max(source.size) > 960 or min(source.size) < 64:
            raise ValueError("Reference dimensions exceed limits")
        image = source.convert("RGB")
    calibration = [(name, (Path(factory_root) / "persist" / name).read_bytes())
                   for name in ("xrservice.json", "device_config.json")]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    destination = directory / "factory/persist"
    destination.mkdir(parents=True)
    for name, data in calibration:
        (destination / name).write_bytes(data)
    reference = directory / "reference"
    reference.mkdir()
    (reference / "photo.png").write_bytes(photo)
    gray = image.convert("L")
    (reference / "photo.pgm").write_bytes(f"P5\n{gray.width} {gray.height}\n255\n".encode() + gray.tobytes())
    (reference / "manifest.tsv").write_text("framephone-recording-v1\nreference\t1\tstatic_reference\t"
                                           + metadata["id"] + "\t-\tphoto.pgm\n")
    config = {"schema": "framephone-photo-session-v1", "phone_session": phone_session, "backend": backend,
              "reference_id": metadata["id"], "calibration_id": "factory-sha256-" + hashlib.sha256(
                  b"".join(data for _, data in calibration)).hexdigest(),
              "left": left, "right": right, "left_stream": left_stream, "right_stream": right_stream,
              "ring": str(ring), "capture_clock": "steam-frame-mono-v4l2", "record": bool(record),
              "clock_alignment": "unverified_no_arcore_or_world_alignment"}
    (directory / "session.json").write_text(json.dumps(config, indent=2) + "\n")
    return config

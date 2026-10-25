"""Small read-only FHRING01 preview. Tracking still uses the native ring reader.

ABI from Frametop commit 24a86dc02669caaef8386ea5bfeb08fcb2819944;
see ../third_party/frametop/LICENSE and camd/fhring.h.
Use pread so a stopped/replaced writer cannot cause mmap/SIGBUS in the GUI.
"""
import os
import struct
import time


def preview(path, name, *, metadata=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        header = os.pread(fd, 1344, 0)
        if len(header) != 1344 or header[:8] != b"FHRING01":
            raise ValueError("camera ring is incomplete")
        version, size, count = struct.unpack_from("<III", header, 8)
        length, _, heartbeat = struct.unpack_from("<QqQ", header, 24)
        if (version != 1 or size != 1344 or not 1 <= count <= 8 or
                length != os.fstat(fd).st_size or not heartbeat or
                abs(time.monotonic_ns() - heartbeat) > 3_000_000_000):
            raise ValueError("camera broker is stopped or ring layout is unsupported")
        for index in range(count):
            offset = 64 + index * 160
            camera = header[offset:offset + 160]
            label = camera[32:64].split(b"\0", 1)[0].decode("utf-8", errors="replace")
            if label != name:
                continue
            fmt, width, height, stride, slots = struct.unpack_from("<IIIII", camera, 68)
            start, slot_bytes, latest = struct.unpack_from("<QQQ", camera, 88)
            pixels = stride * height
            if (fmt or not 0 < width <= 4096 or not 0 < height <= 4096 or
                    not width <= stride <= 32768 or not 1 <= slots <= 64 or pixels > 16_777_216 or
                    start < size or slot_bytes < 64 + pixels or
                    start + slots * slot_bytes > length):
                raise ValueError("unsupported preview image layout")
            if not latest:
                return None
            position = start + (latest % slots) * slot_bytes
            data = os.pread(fd, 64 + pixels, position)
            if len(data) != 64 + pixels:
                return None
            seq, frame = struct.unpack_from("<QQ", data)
            again = os.pread(fd, 8, position)
            if seq != latest * 2 + 2 or frame != latest or again != data[:8]:
                return None
            gray = data[64:] if stride == width else b"".join(
                data[64+y*stride:64+y*stride+width] for y in range(height))
            result = (width, height, f"P5\n{width} {height}\n255\n".encode() + gray)
            if metadata:
                capture = struct.unpack_from("<Q", data, 16)[0]
                return (*result, {"camera_id": name, "sequence": frame,
                                 "capture_timestamp_ns": capture,
                                 "publish_monotonic_ns": struct.unpack_from("<Q", data, 32)[0],
                                 "clock": "steam-frame-mono-v4l2"})
            return result
        return None
    finally:
        os.close(fd)

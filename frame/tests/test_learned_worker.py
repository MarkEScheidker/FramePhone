"""Framing validation does not need PyTorch, a camera or downloaded models."""
import io
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from learned_worker import read_exact, read_message, send_message


class FramingTests(unittest.TestCase):
    def test_roundtrip_and_binary_boundary(self):
        stream = io.BytesIO()
        send_message(stream, {"op": "match", "sequence": 3})
        stream.write(b"\x00\xff\n\x01")
        stream.seek(0)
        self.assertEqual(read_message(stream), {"op": "match", "sequence": 3})
        self.assertEqual(read_exact(stream, 4), b"\x00\xff\n\x01")
        self.assertIsNone(read_message(stream))

    def test_truncation_and_oversize(self):
        for data in (b"\0", struct.pack("!I", 0), struct.pack("!I", 65537)):
            with self.assertRaises(ValueError):
                read_message(io.BytesIO(data))
        with self.assertRaises(EOFError):
            read_message(io.BytesIO(struct.pack("!I", 5) + b"{}"))
        with self.assertRaises(json.JSONDecodeError):
            read_message(io.BytesIO(struct.pack("!I", 1) + b"!"))

    def test_response_limits_and_nonfinite(self):
        with self.assertRaises(ValueError):
            send_message(io.BytesIO(), {"x": float("nan")})
        with self.assertRaises(ValueError):
            send_message(io.BytesIO(), {"x": "x" * (2 * 1024 * 1024)})


if __name__ == "__main__":
    unittest.main()

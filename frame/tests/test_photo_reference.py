"""Photo wire bounds, identity/integrity and state; no Pillow needed for these tests."""
import base64
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from photo_reference import PhotoReceiver, MAX_PHOTO


def png():
    def chunk(kind, data):
        return struct.pack("!I",len(data)) + kind + data + struct.pack("!I",zlib.crc32(kind+data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR",struct.pack("!IIBBBBB",64,64,8,0,0,0,0)) +
            chunk(b"IDAT",zlib.compress((b"\0"+bytes(range(64)))*64)) + chunk(b"IEND",b""))


def messages(request, data=None):
    data = png() if data is None else data
    identity = hashlib.sha256(data).hexdigest()
    return [{"type":"photo_begin","request":request,"id":identity,"size":len(data),"width":64,"height":64},
            {"type":"photo_chunk","request":request,"offset":0,"data":base64.b64encode(data).decode()},
            {"type":"photo_end","request":request}]


class PhotoTests(unittest.TestCase):
    def test_exact_reference_and_display_state(self):
        receiver=PhotoReceiver()
        request=receiver.begin_request()["request"]
        for message in messages(request): receiver.receive(message)
        self.assertEqual(receiver.data,png())
        self.assertEqual(receiver.metadata["id"],hashlib.sha256(png()).hexdigest())
        self.assertFalse(receiver.snapshot()["downloading"])
        receiver.receive({"type":"photo_state","id":receiver.metadata["id"],"displayed":True})
        self.assertTrue(receiver.snapshot()["state"]["displayed"])

    def test_no_unsolicited_or_overlapping_downloads(self):
        r=PhotoReceiver()
        with self.assertRaises(ValueError): r.receive(messages("x")[0])
        r.begin_request()
        with self.assertRaises(ValueError): r.begin_request()

    def test_bounds_and_order(self):
        for field,value in (("size",MAX_PHOTO+1),("width",10000),("height",True)):
            r=PhotoReceiver(); request=r.begin_request()["request"]
            first=messages(request)[0]; first[field]=value
            with self.assertRaises(ValueError): r.receive(first)
        r=PhotoReceiver(); request=r.begin_request()["request"]
        first,chunk,end=messages(request)
        r.receive(first); chunk["offset"]=1
        with self.assertRaises(ValueError): r.receive(chunk)
        with self.assertRaises(ValueError): r.receive(end)

    def test_corrupt_data_and_dimensions_never_publish(self):
        for change in ("hash","dimensions"):
            r=PhotoReceiver(); request=r.begin_request()["request"]
            first,chunk,end=messages(request)
            first["id"]="0"*64 if change=="hash" else first["id"]
            if change=="dimensions": first["width"]=65
            r.receive(first); r.receive(chunk)
            with self.assertRaises(ValueError): r.receive(end)
            self.assertIsNone(r.data)

    def test_missing_photo_can_retry(self):
        r=PhotoReceiver(); request=r.begin_request()["request"]
        r.receive({"type":"photo_missing","request":request})
        self.assertIn("Choose",r.error)
        self.assertNotEqual(request,r.begin_request()["request"])

    def test_display_state_expires_without_heartbeat(self):
        r=PhotoReceiver()
        with patch("photo_reference.time.monotonic",return_value=10):
            r.receive({"type":"photo_state","id":"a"*64,"displayed":True})
        with patch("photo_reference.time.monotonic",return_value=12):
            self.assertFalse(r.snapshot()["state"]["displayed"])


if __name__=="__main__": unittest.main()

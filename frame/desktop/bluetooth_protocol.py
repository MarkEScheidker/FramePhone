"""BLE wire and trust boundary; no D-Bus, GUI or radio dependencies."""
import hashlib
import hmac
import ipaddress
import json
import math
import struct
import time
import uuid

SERVICE = 'f7a10001-81a6-4c44-9c79-99ac54174901'
CONTROL = 'f7a10002-81a6-4c44-9c79-99ac54174901'
POSE = 'f7a10003-81a6-4c44-9c79-99ac54174901'
HEADER = struct.Struct('<4sBBBB16s16s16sQQQQ7f')
GYRO = struct.Struct('<Q3f')
STATES = ('tracking', 'paused', 'error', 'stopped')
REASONS = ('', 'headset_not_worn', 'user_dismissed', 'screen_locked', 'camera_in_use')


def transcript(challenge, address, pin, host):
    return f'framephone-bt-bootstrap-v1\n{challenge}\n{address.upper()}\n{pin}\n{host}\n47643\n'.encode('ascii')


def bootstrap(message, challenge, address, saved, enroll):
    """The caller guarantees authenticated/encrypted GATT writes and a fresh challenge."""
    if message.get('op') != 'bootstrap' or message.get('challenge') != challenge:
        raise ValueError('Invalid Bluetooth bootstrap challenge')
    pin, proof, host = (message.get(k) for k in ('pin', 'proof', 'host'))
    if any(not isinstance(x, str) or len(x) != 64 or any(c not in '0123456789abcdef' for c in x)
           for x in (pin, proof)):
        raise ValueError('Invalid Bluetooth identity/proof')
    route = ipaddress.IPv4Address(host)
    if route.is_loopback or route.is_multicast or route.is_unspecified or route.is_link_local:
        raise ValueError('Invalid LAN route')
    credential = saved['credential'] if saved else message.get('credential', '')
    if not saved and not enroll:
        raise ValueError('Open Bluetooth pairing on Frame first')
    if (not isinstance(credential, str) or len(credential) != 64 or
            any(c not in '0123456789abcdef' for c in credential)):
        raise ValueError('Invalid application credential')
    if saved and not hmac.compare_digest(pin, saved['pin']):
        raise ValueError('Phone identity changed; explicit new pairing required')
    key = hashlib.sha256(credential.encode('ascii')).digest()
    expected = hmac.new(key, transcript(challenge, address, pin, host), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, proof):
        raise ValueError('Bluetooth application authentication failed')
    return dict(saved or {}, pin=pin, credential=credential, host=host)


def decode_pose(data):
    if not HEADER.size <= len(data) <= 512:
        raise ValueError('Invalid BLE pose size')
    magic, version, flags, code, count, session, generation, acquisition, seq, stamp, frame, capture, *values = HEADER.unpack_from(data)
    state, reason = code & 15, code >> 4
    if (magic != b'FPBT' or version != 1 or flags & ~3 or state >= len(STATES) or reason >= len(REASONS) or count > 19 or
            len(data) != HEADER.size+count*GYRO.size or not 0 < seq < 2**63 or not 0 < stamp < 2**63 or frame >= 2**63):
        raise ValueError('Invalid BLE pose header')
    message = dict(type='arcore_pose', session=str(uuid.UUID(bytes=session)),
                   generation=str(uuid.UUID(bytes=generation)), acquisition=str(uuid.UUID(bytes=acquisition)),
                   seq=seq, t_ns=stamp, frame_timestamp_ns=frame, state=STATES[state],
                   marker_required=bool(flags & 1), reason=REASONS[reason], transform='T_AD', time_source='update_elapsed_realtime_ns')
    if state == 0:
        if any(not math.isfinite(x) for x in values) or abs(sum(x*x for x in values[3:])-1) > .002:
            raise ValueError('Invalid BLE pose transform')
        message.update(translation_m=values[:3], quaternion_xyzw=values[3:])
        if flags & 2:
            if not 0 <= stamp-capture <= 200_000_000:
                raise ValueError('Invalid BLE capture clock')
            message.update(capture_t_ns=capture, capture_time_source='camera2_realtime_center_exposure')
    gyro = []
    previous = -1
    for i in range(count):
        timestamp, *w = GYRO.unpack_from(data, HEADER.size+i*GYRO.size)
        if (not previous < timestamp < 2**63 or not -200_000_000 <= timestamp-stamp <= 250_000_000 or
                any(not math.isfinite(x) for x in w) or math.hypot(*w) > 35):
            raise ValueError('Invalid BLE gyro samples')
        gyro.append(dict(t_ns=timestamp, w_rad_s=w))
        previous = timestamp
    return message, gyro


class ControlFragments:
    """One bounded control message per device; partial messages expire."""
    def __init__(self):
        self.pending = {}

    def receive(self, device, value, now=None):
        now = time.monotonic() if now is None else now
        self.pending = {k: v for k, v in self.pending.items() if now-v[0] < 3}
        if len(value) < 6:
            raise ValueError('Invalid Bluetooth control fragment')
        ident, offset, total = struct.unpack_from('<HHH', value)
        if not 0 < total <= 1024 or offset+len(value)-6 > total:
            raise ValueError('Bluetooth control size exceeds limit')
        if offset == 0:
            if device not in self.pending and len(self.pending) >= 4:
                raise ValueError('Too many Bluetooth control clients')
            self.pending[device] = (now, ident, total, bytearray())
        entry = self.pending.get(device)
        if not entry or entry[1:3] != (ident, total) or len(entry[3]) != offset:
            raise ValueError('Out-of-order Bluetooth control fragment')
        entry[3].extend(value[6:])
        if len(entry[3]) != total:
            return None
        del self.pending[device]
        message = json.loads(entry[3])
        if not isinstance(message, dict):
            raise ValueError('Expected Bluetooth control object')
        return message

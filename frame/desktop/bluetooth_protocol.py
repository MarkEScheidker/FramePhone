"""BLE wire and trust boundary; no D-Bus, GUI or radio dependencies."""
import math
import struct
import time
import uuid

SERVICE = 'f7a10001-81a6-4c44-9c79-99ac54174901'
CONTROL = 'f7a10002-81a6-4c44-9c79-99ac54174901'
POSE = 'f7a10003-81a6-4c44-9c79-99ac54174901'
HEADER = struct.Struct('<4sBBBB16s16s16sQQQQ7f')
GYRO = struct.Struct('<Q3f')
GYRO_HEADER = struct.Struct('<4sB16s16s16sB')
STATES = ('tracking', 'paused', 'error', 'stopped')
REASONS = ('', 'headset_not_worn', 'user_dismissed', 'screen_locked', 'camera_in_use')


def decode_gyro(data):
    if len(data) < GYRO_HEADER.size:
        raise ValueError('Invalid BLE gyro size')
    magic, version, session, generation, acquisition, count = GYRO_HEADER.unpack_from(data)
    if magic != b'FPIM' or version != 1 or not 1 <= count <= 19 or len(data) != GYRO_HEADER.size+count*GYRO.size:
        raise ValueError('Invalid BLE gyro header')
    samples = []
    previous = 0
    for i in range(count):
        stamp, *w = GYRO.unpack_from(data, GYRO_HEADER.size+i*GYRO.size)
        if not previous < stamp < 2**63 or any(not math.isfinite(x) for x in w) or math.hypot(*w) > 35:
            raise ValueError('Invalid BLE gyro samples')
        samples.append(dict(t_ns=stamp, w_rad_s=w))
        previous = stamp
    return dict(type='gyro_samples', session=str(uuid.UUID(bytes=session)),
                generation=str(uuid.UUID(bytes=generation)), acquisition=str(uuid.UUID(bytes=acquisition))), samples


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
        if not 0 < total <= 32768 or offset+len(value)-6 > total:
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
            self.pending[device] = (now, ident, total, entry[3])
            return None
        del self.pending[device]
        return bytes(entry[3])

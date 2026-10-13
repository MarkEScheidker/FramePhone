"""Exercise the headset CLI with an independent two-camera ring producer."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time

binary, fixtures = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from front_cameras import parse_progress
base = [str(binary), '--factory-root', str(fixtures / 'stereo-factory'),
        '--calibration-id', 'synthetic-factory-v1']


def run(args, success=True):
    result = subprocess.run(base + args, text=True, capture_output=True, timeout=15)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


assert 'slam_left' in run(['--list-cameras']).stdout
run(['--list-cameras', '--ring', '/bad'], False)
run(['--ring', '/bad', '--left', 'slam_left', '--right', 'slam_right',
     '--phone-layout', str(fixtures / 'synthetic-phone-layout.json')], False)

with tempfile.TemporaryDirectory(prefix='framephone-stereo-cli-') as directory:
    root = Path(directory)
    ring = root / 'ring'
    slot_bytes = 64 + 640 * 480
    offsets = [1344, 1344 + slot_bytes]
    size = offsets[1] + slot_bytes
    data = bytearray(size)
    struct.pack_into('<8sIIIIQQQ', data, 0, b'FHRING01', 1, 1344, 2, 0, size,
                     os.getpid(), time.monotonic_ns())
    for index, name in enumerate(['sensor_left_video13', 'sensor_right_video9']):
        off = 64 + index * 160
        data[off:off+4] = b'test'
        data[off+32:off+32+len(name)] = name.encode()
        struct.pack_into('<IIIIIIQQQQQ', data, off+64, index, 0, 640, 480, 640, 1,
                         offsets[index], slot_bytes, 0, 0, 0)
    ring.write_bytes(data)
    listed = subprocess.run([str(binary), '--list-ring', str(ring)], text=True,
                            capture_output=True, timeout=5)
    assert listed.returncode == 0 and 'sensor_left_video13' in listed.stdout, listed.stderr
    done = threading.Event()

    def publish():
        with ring.open('r+b', buffering=0) as f:
            n = 0
            while not done.is_set():
                n += 1
                f.seek(40)
                f.write(struct.pack('<Q', time.monotonic_ns()))
                for index in range(2):
                    # Equal source clock plus 100 us right offset. Blank images
                    # must produce loss records, never fabricated/held poses.
                    cap = 10**16 + n * 33333333 + index * 100000
                    f.seek(offsets[index])
                    f.write(struct.pack('<QQQQQIf', 2*n+1, n, cap, time.monotonic_ns(),
                                        time.monotonic_ns(), n, 24.0))
                    f.seek(offsets[index]+64)
                    f.write(bytes([24]) * (640*480))
                    f.seek(offsets[index])
                    f.write(struct.pack('<Q', 2*n+2))
                    f.seek(64 + index*160 + 104)
                    f.write(struct.pack('<QQ', n, n))
                done.wait(.025)

    writer = threading.Thread(target=publish)
    writer.start()
    args = ['--ring', str(ring), '--left', 'slam_left', '--right', 'slam_right',
            '--left-ring', 'sensor_left_video13', '--right-ring', 'sensor_right_video9',
            '--phone-layout', str(fixtures / 'synthetic-phone-layout.json'),
            '--capture-clock', 'synthetic-shared', '--frames', '3']
    try:
        result = run(args + ['--pose-jsonl', str(root/'pose.jsonl'), '--csv', str(root/'tags.csv'),
                             '--record-dir', str(root/'recording')])
    finally:
        done.set()
        writer.join()
    rows = [json.loads(line) for line in (root/'pose.jsonl').read_text().splitlines()]
    assert len(rows) == 3 and all(r['status'] == 'insufficient_tags' for r in rows)
    assert all(r['capture_skew_ns'] == 100000 and not r['candidates'] for r in rows)
    assert all(r['frames'][0]['capture_timestamp_ns'] > 2**53 for r in rows)
    assert all('ring_transport' in r['frames'][0] for r in rows)
    assert all(r['frames'][0]['camera_id'] == 'sensor_left_video13' and
               r['frames'][0]['factory_camera_id'] == 'slam_left' for r in rows)
    assert len(list((root/'recording').glob('*.pgm'))) == 6
    replay = ['--replay', str(root/'recording'), '--left', 'slam_left', '--right', 'slam_right',
              '--left-ring', 'sensor_left_video13', '--right-ring', 'sensor_right_video9',
              '--phone-layout', str(fixtures / 'synthetic-phone-layout.json')]
    assert 'pairs=3 accepted=0' in run(replay).stdout
    run(replay + ['--pose-jsonl', str(root/'pose.jsonl')], False)
    assert 'pairs=3 accepted=0' in result.stdout
    progress = [parse_progress(line) for line in result.stdout.splitlines() if line.startswith('pair=')]
    assert len(progress) == 3 and all(p['status'] == 'insufficient_tags' for p in progress), result.stdout
    assert all(p['views'][0]['count'] == 0 and p['views'][1]['ids'] == [] for p in progress)

print('Stereo live ring, exports, raw recording, replay and CLI validation passed')

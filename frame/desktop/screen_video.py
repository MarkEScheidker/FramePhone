"""Authenticated video receiver; decoding and RAM-only publication never touch pose locks."""
import hashlib
import hmac
import json
import mmap
import os
from contextlib import contextmanager
from pathlib import Path
import platform
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import fcntl

PORT = 47644
MAX_PACKET = 2 * 1024 * 1024
MAX_PIXELS = 2_000_000
HEADER = 64
MAGIC = b'FPSCRN01'
# Access-unit delimiter, primary_pic_type=7. Android delivers complete access
# units, but FFmpeg's byte-stream parser otherwise waits for the following frame
# to discover that the current one ended. A delimiter makes that boundary explicit.
ACCESS_UNIT_END = b'\x00\x00\x00\x01\x09\xf0'


def exact(source, count):
    data = bytearray()
    while len(data) < count:
        chunk = source.recv(count-len(data))
        if not chunk:
            raise ConnectionError('Video connection ended')
        data.extend(chunk)
    return bytes(data)


def read_packet(source):
    length, flags, pts = struct.unpack('!IIQ', exact(source, 16))
    if (length > MAX_PACKET or flags not in (0, 1, 2, 4) or
            (length == 0) != (flags == 4) or pts > 0x7fffffffffffffff or
            (flags == 4 and pts not in (0, 1))):
        raise ValueError('Invalid encrypted video packet')
    return flags, pts, exact(source, length)


def descriptor(value):
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value.get('version') != 1 or
            type(value.get('port')) is not int or value.get('port') != PORT or
            not isinstance(value.get('token'), str) or len(value['token']) != 64 or
            any(c not in '0123456789abcdef' for c in value['token'])):
        raise ValueError('Invalid screen video capability')
    return dict(value)


def video_format(value, session):
    if value.get('type') != 'video_ready' or value.get('version') != 1 or value.get('codec') != 'h264' or value.get('session') != session:
        raise ValueError('Unsupported video stream')
    w, h, rotation = value.get('width'), value.get('height'), value.get('rotation')
    if (type(w) is not int or type(h) is not int or not 16 <= w <= 4096 or
            not 16 <= h <= 4096 or w*h > MAX_PIXELS or type(rotation) is not int or rotation not in range(4)):
        raise ValueError('Invalid video dimensions')
    return w, h, rotation


class ScreenFrames:
    """One latest RGBA frame in private tmpfs; flock prevents torn ARM reads.

    Header: magic[8], LE width/height u32, sequence/time u64, length/active u32.
    The renderer takes a nonblocking shared lock and copies before releasing it.
    No screenshot data goes into the diagnostic recording directory.
    """
    def __init__(self, metadata):
        self.folder = tempfile.TemporaryDirectory(prefix='framephone-screen-', dir='/dev/shm')
        self.path = Path(self.folder.name)/'rgba'
        self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.ftruncate(self.fd, HEADER + MAX_PIXELS*4)
        self.memory = mmap.mmap(self.fd, 0)
        self.sequence = 0
        self.epoch = 1
        self.lock = threading.Lock()
        self.metadata = Path(metadata)
        temporary = self.metadata.with_suffix('.tmp')
        temporary.write_text(json.dumps({'schema': 'framephone-screen-v1', 'path': str(self.path)}))
        temporary.replace(self.metadata)

    @contextmanager
    def _write(self):
        # flock protects the separate renderer process; a mutex also serializes
        # our decoder/transport threads, which share one open file description.
        with self.lock:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(self.fd, fcntl.LOCK_UN)

    def publish(self, rgba, width, height):
        if len(rgba) != width*height*4 or width*height > MAX_PIXELS:
            raise ValueError('Invalid decoded frame')
        with self._write():
            self.memory[HEADER:HEADER+len(rgba)] = rgba
            self.sequence += 1
            struct.pack_into('<8sIIQQII', self.memory, 0, MAGIC, width, height,
                             self.sequence, time.monotonic_ns(), len(rgba), 1)
            struct.pack_into('<Q', self.memory, 40, self.epoch)

    def keep_alive(self):
        # A static display may emit no new encoded frames. This renews validity,
        # not capture/decode time, and can never resurrect a cleared publication.
        with self._write():
            if self.sequence and struct.unpack_from('<I', self.memory, 36)[0] == 1:
                struct.pack_into('<Q', self.memory, 24, time.monotonic_ns())

    def clear(self):
        with self._write():
            struct.pack_into('<I', self.memory, 36, 0)
            self.epoch += 1
            struct.pack_into('<Q', self.memory, 40, self.epoch)

    def close(self):
        self.clear()
        self.memory.close()
        os.close(self.fd)
        try:
            if json.loads(self.metadata.read_text()).get('path') == str(self.path):
                self.metadata.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        self.folder.cleanup()


def decoder_base():
    override = os.environ.get('FRAMEPHONE_FFMPEG')
    if override:
        return [override], os.environ.copy(), False
    host = Path('/usr/bin/ffmpeg')
    if host.is_file():
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'PYTHON', 'TCL_', 'TK_', 'FRAMEPHONE_'))}
        return [str(host)], env, platform.machine() in ('aarch64', 'arm64')
    root = os.environ.get('FRAMEPHONE_RUNTIME_ROOT')
    if root:
        # libavdevice links PulseAudio; libpulsecommon lives below the ordinary
        # library path and its ELF RUNPATH otherwise points outside the bundle.
        extra = sorted(str(p) for p in (Path(root)/'usr/lib').glob('*-linux-gnu/pulseaudio'))
        libraries = ':'.join([os.environ['FRAMEPHONE_LIBRARY_PATH'], *extra])
        env = dict(os.environ, LD_LIBRARY_PATH=libraries)
        return [os.environ['FRAMEPHONE_LOADER'], '--library-path', libraries,
                str(Path(root)/'usr/bin/ffmpeg')], env, False
    raise OSError('FFmpeg missing; rebuild the Frame package or install ffmpeg for a development run')


class ScreenVideo:
    def __init__(self, host, pin, session, capability, metadata):
        self.host, self.pin, self.session = host, pin, session
        self.capability = descriptor(capability)
        self.frames = ScreenFrames(metadata)
        self.stopped = threading.Event()
        self.sock = self.process = None
        self.status = 'Waiting for screen capture'
        self.hardware_failed = False
        self.decoded = 0
        self.decoder_error = ''
        self.thread = threading.Thread(target=self._run, name='screen-video', daemon=True)
        self.thread.start()

    def _decode(self, sock, profile):
        self.decoder_error = ''
        width, height, rotation = video_format(profile, self.session)
        command, env, hardware = decoder_base()
        hardware = hardware and not self.hardware_failed
        command += ['-hide_banner', '-loglevel', 'error', '-nostdin', '-filter_threads', '1', '-probesize', '32',
                    '-analyzeduration', '0', '-fpsprobesize', '0', '-flags', 'low_delay',
                    '-thread_type', 'slice', '-threads', '2', '-max_pixels', str(MAX_PIXELS)]
        if hardware:
            command += ['-c:v', 'h264_v4l2m2m']
        command += ['-f', 'h264', '-i', 'pipe:0', '-an', '-sn', '-dn']
        filters = {1: 'transpose=clock', 2: 'hflip,vflip', 3: 'transpose=cclock'}
        transform = f'scale={width}:{height}:flags=fast_bilinear'
        if rotation:
            transform += ',' + filters[rotation]
        command += ['-vf', transform]
        # Rawvideo's frame-threaded encoder can itself queue several frames.
        # Flush each image, including a small/static image below the IO buffer size.
        command += ['-vsync', '0', '-pix_fmt', 'rgba', '-threads', '1',
                    '-flush_packets', '1', '-f', 'rawvideo', 'pipe:1']
        out_w, out_h = (height, width) if rotation % 2 else (width, height)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, bufsize=0)
        self.process = process
        self.status = 'Starting screen decoder'
        ended = threading.Event()
        began = time.monotonic()
        progress = [began]
        input_at = [0.0]
        errors = []
        count = [0]
        stalled = threading.Event()

        def output():
            try:
                size = out_w*out_h*4
                report_at, report_count, fps = time.monotonic(), 0, None
                while not self.stopped.is_set() and not ended.is_set():
                    data = bytearray()
                    while len(data) < size:
                        chunk = process.stdout.read(size-len(data))
                        if not chunk:
                            return
                        data.extend(chunk)
                    self.frames.publish(data, out_w, out_h)
                    progress[0] = time.monotonic()
                    count[0] += 1
                    self.decoded += 1
                    if progress[0] - report_at >= 1:
                        fps = (count[0] - report_count) / (progress[0] - report_at)
                        report_at, report_count = progress[0], count[0]
                    rate = f' · {fps:.1f} FPS' if fps is not None else ''
                    self.status = f'Screen streaming · {out_w}×{out_h} · {"hardware" if hardware else "software"} decode{rate}'
            except (OSError, ValueError):
                pass
            finally:
                ended.set()
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass

        def error_output():
            for line in process.stderr:
                errors.append(line.decode(errors='replace').strip()[:160])
                if len(errors) > 8:
                    errors.pop(0)

        def watchdog():
            while not ended.wait(.25) and not self.stopped.is_set():
                if ((input_at[0] > progress[0] and time.monotonic()-progress[0] > 3) or
                        (not count[0] and time.monotonic()-began > 6)):
                    stalled.set()
                    process.kill()
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    return
        readers = [threading.Thread(target=target, daemon=True) for target in (output, error_output, watchdog)]
        for reader in readers: reader.start()
        try:
            configured = False
            while not self.stopped.is_set() and not ended.is_set():
                flags, pts, packet = read_packet(sock)
                if flags == 4:
                    if pts == 1 and count[0] and input_at[0] <= progress[0]:
                        self.frames.keep_alive()
                    continue
                if flags == 1:
                    configured = True
                elif not configured:
                    raise ValueError('Video frame before codec configuration')
                if flags != 1:
                    input_at[0] = time.monotonic()
                    packet += ACCESS_UNIT_END
                view = memoryview(packet)
                while view and not self.stopped.is_set():
                    written = process.stdin.write(view)
                    if not written:
                        raise ConnectionError('Video decoder closed input')
                    view = view[written:]
        finally:
            ended.set()
            crashed = process.poll() not in (None, 0)
            process.kill()
            process.wait(timeout=2)
            for reader in readers: reader.join(timeout=1)
            for pipe in (process.stdin, process.stdout, process.stderr): pipe.close()
            self.process = None
            self.frames.clear()
            if hardware and (not count[0] or crashed or stalled.is_set()):
                self.hardware_failed = True
            if errors and not self.stopped.is_set():
                self.decoder_error = errors[-1]
                self.status = 'Video decoder: ' + self.decoder_error

    def _run(self):
        from phone_link import read_message, write_message
        try:
            while not self.stopped.is_set():
                try:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.minimum_version = ssl.TLSVersion.TLSv1_3
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    with socket.create_connection((self.host, PORT), timeout=4) as raw:
                        self.sock = raw
                        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
                        with context.wrap_socket(raw) as sock:
                            self.sock = sock
                            if not hmac.compare_digest(hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest(), self.pin):
                                self.status = 'Screen stopped: phone certificate changed'
                                return  # No session token is sent to an unverified peer.
                            sock.settimeout(3)
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                            write_message(sock, {'type': 'screen_video', 'version': 1,
                                                 'session': self.session, 'token': self.capability['token']})
                            profile = read_message(sock)
                            if profile.get('type') == 'video_wait':
                                self.status = 'Approve screen sharing on phone' if profile.get('reason') == 'Approve screen sharing on phone' else 'Screen waiting for tracking'
                            else:
                                self._decode(sock, profile)
                except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
                    if not self.stopped.is_set():
                        self.status = ('Video decoder: ' + self.decoder_error) if self.decoder_error else 'Video reconnecting: ' + (str(error)[:120] if isinstance(error, OSError) else 'invalid video stream')
                finally:
                    self.sock = None
                    self.frames.clear()
                self.stopped.wait(1)
        finally:
            self.frames.close()

    def close(self):
        self.stopped.set()
        sock, process = self.sock, self.process
        if sock:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            sock.close()
        if process:
            try: process.kill()
            except OSError: pass
        self.thread.join(timeout=5)

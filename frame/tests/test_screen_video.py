"""Video framing, private publication and real pinned-TLS/FFmpeg integration."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'desktop'))
from phone_link import read_message, write_message
from screen_video import PORT, ScreenFrames, ScreenVideo, descriptor, video_format, decoder_base, read_packet, MAX_PACKET


class ScreenProtocolTests(unittest.TestCase):
    def test_fragmented_packets_and_limits_before_body_allocation(self):
        import io
        class Peer:
            def __init__(self, data): self.data = io.BytesIO(data)
            def recv(self, size): return self.data.read(min(size, 1))
        wire=struct.pack('!IIQ',5,2,9_007_199_254_740_993)+b'frame'
        self.assertEqual(read_packet(Peer(wire)),(2,9_007_199_254_740_993,b'frame'))
        for length,flags,pts in ((MAX_PACKET+1,0,0),(0,0,0),(1,4,0),(0,4,2),(2,3,0),(1,0,2**63)):
            with self.assertRaises(ValueError):read_packet(Peer(struct.pack('!IIQ',length,flags,pts)))

    def test_bundled_decoder_keeps_nested_runtime_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            pulse=Path(folder)/'usr/lib/aarch64-linux-gnu/pulseaudio'
            pulse.mkdir(parents=True)
            with patch.dict(os.environ, {'FRAMEPHONE_RUNTIME_ROOT':folder,
                    'FRAMEPHONE_LOADER':'/bundle/loader','FRAMEPHONE_LIBRARY_PATH':'/bundle/lib'},clear=True), \
                    patch('screen_video.Path.is_file',return_value=False):
                command,env,hardware=decoder_base()
            self.assertIn(str(pulse),env['LD_LIBRARY_PATH'])
            self.assertEqual(command[2],env['LD_LIBRARY_PATH'])
            self.assertFalse(hardware)

    def test_bounds_and_session_validation(self):
        good={'version': 1, 'port': PORT, 'token': 'a'*64}
        self.assertEqual(descriptor(good),good)
        for bad in ({'port':1},{'token':'bad'},{'version':True}):
            with self.assertRaises(ValueError): descriptor(dict(good,**bad))
        ready={'type':'video_ready','version':1,'codec':'h264','session':'s','width':64,'height':96,'rotation':0}
        self.assertEqual(video_format(ready,'s'),(64,96,0))
        for bad in ({'width':True},{'height':10000},{'width':2000,'height':2000},{'rotation':4},{'session':'old'}):
            with self.assertRaises(ValueError): video_format(dict(ready,**bad),'s')

    def test_private_ram_frame_epoch_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            metadata=Path(folder)/'screen.json'
            frames=ScreenFrames(metadata)
            path=frames.path
            try:
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777,0o700)
                frames.publish(bytes([12,34,56,255])*16*32,16,32)
                magic,w,h,seq,stamp,size,active=struct.unpack_from('<8sIIQQII',frames.memory)
                self.assertEqual((magic,w,h,seq,size,active),(b'FPSCRN01',16,32,1,2048,1))
                self.assertGreater(stamp,0)
                time.sleep(.002); frames.keep_alive()
                self.assertGreater(struct.unpack_from('<Q',frames.memory,24)[0],stamp)
                epoch=struct.unpack_from('<Q',frames.memory,40)[0]
                frames.clear()
                frames.keep_alive()
                self.assertEqual(struct.unpack_from('<I',frames.memory,36)[0],0)
                self.assertGreater(struct.unpack_from('<Q',frames.memory,40)[0],epoch)
                with self.assertRaises(ValueError):frames.publish(b'short',16,32)
            finally: frames.close()
            self.assertFalse(path.exists())
            self.assertFalse(metadata.exists())

    def test_recording_excludes_screen_authorization(self):
        from telemetry_recording import evidence_message
        from test_phone_link import profile
        value=profile(); value['screen_video_v1']={'token':'never-log-video-token','port':PORT,'version':1}
        self.assertNotIn('never-log-video-token',json.dumps(evidence_message(value)))


class VideoTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory()
        root=Path(cls.folder.name)
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=screen-test','-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem')],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        cls.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.context.minimum_version=ssl.TLSVersion.TLSv1_3
        cls.context.load_cert_chain(root/'cert.pem',root/'key.pem')
        cls.pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert((root/'cert.pem').read_text())).hexdigest()

    @classmethod
    def tearDownClass(cls):cls.folder.cleanup()

    def server(self, action):
        listener=socket.socket()
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
        errors=[]
        def run():
            try:
                raw,_=listener.accept()
                with raw, self.context.wrap_socket(raw,server_side=True) as peer:
                    peer.settimeout(4);action(peer)
            except (ConnectionError,ssl.SSLError):pass
            except BaseException as error:errors.append(error)
            finally:listener.close()
        thread=threading.Thread(target=run,daemon=True);thread.start()
        return listener.getsockname()[1],thread,errors

    def receiver(self, port, metadata, pin=None):
        original=socket.create_connection
        def connect(address,**kwargs):return original((address[0],port),**kwargs)
        redirect=patch('screen_video.socket.create_connection',connect)
        redirect.start()
        self.addCleanup(redirect.stop)
        return ScreenVideo('127.0.0.1',pin or self.pin,'test',{'version':1,'port':PORT,'token':'a'*64},metadata)

    def test_wrong_pin_sends_no_video_token(self):
        received=[]
        port,thread,errors=self.server(lambda peer:received.append(peer.recv(4096)))
        with tempfile.TemporaryDirectory() as folder:
            receiver=self.receiver(port,Path(folder)/'screen.json','0'*64)
            receiver.thread.join(4)
            self.assertFalse(receiver.thread.is_alive())
            self.assertIn('certificate changed',receiver.status)
            receiver.close()
        thread.join(4)
        self.assertEqual(errors,[])
        self.assertTrue(not received or received==[b''])

    def test_capture_wait_is_not_a_tracking_failure(self):
        def reply(peer):
            message=read_message(peer)
            self.assertEqual(message['session'],'test');self.assertEqual(message['token'],'a'*64)
            write_message(peer,{'type':'video_wait','reason':'Approve screen sharing on phone'})
        port,thread,errors=self.server(reply)
        with tempfile.TemporaryDirectory() as folder:
            receiver=self.receiver(port,Path(folder)/'screen.json')
            limit=time.monotonic()+3
            while 'Approve' not in receiver.status and time.monotonic()<limit:time.sleep(.01)
            self.assertIn('Approve',receiver.status)
            self.assertEqual(receiver.decoded,0)
            receiver.close()
        thread.join(4);self.assertEqual(errors,[])

    @unittest.skipUnless(os.environ.get('FRAMEPHONE_FFMPEG') or shutil.which('ffmpeg'),'FFmpeg integration runs in native CI/package checks')
    def test_each_predicted_frame_displays_before_the_next_access_unit(self):
        command,env,_=decoder_base()
        clip=subprocess.check_output([*command,'-hide_banner','-loglevel','error','-filter_threads','1',
            '-f','lavfi','-i','testsrc=size=64x96:rate=30','-frames:v','3','-c:v','libx264',
            '-threads','1','-preset','ultrafast','-tune','zerolatency','-x264-params','aud=1',
            '-g','30','-bf','0','-pix_fmt','yuv420p','-f','h264','pipe:1'],env=env)
        units=[unit for unit in re.split(b'(?=\x00\x00\x00\x01\x09)',clip) if unit]
        self.assertEqual(len(units),3)
        nals=[nal for nal in re.split(b'\x00\x00(?:\x00)?\x01',units[0]) if nal]
        config=b''.join(b'\x00\x00\x00\x01'+nal for nal in nals if nal[0]&31 in (7,8))
        self.assertTrue(config)
        self.assertTrue(any(nal and nal[0]&31==1 for nal in re.split(b'\x00\x00(?:\x00)?\x01',units[1])))
        advance,done=threading.Event(),threading.Event()
        def send(peer):
            read_message(peer)
            write_message(peer,{'type':'video_ready','version':1,'session':'test','codec':'h264',
                                'generation':'paced','width':64,'height':96,'rotation':1})
            peer.sendall(struct.pack('!IIQ',len(config),1,0)+config)
            for i,unit in enumerate(units):
                peer.sendall(struct.pack('!IIQ',len(unit),2 if i==0 else 0,i*33333)+unit)
                if not advance.wait(3): raise AssertionError('Decoder waited for a later frame')
                advance.clear()
            done.wait(3)
        port,thread,errors=self.server(send)
        with tempfile.TemporaryDirectory() as folder:
            receiver=self.receiver(port,Path(folder)/'screen.json')
            try:
                previous=None
                for i in range(3):
                    limit=time.monotonic()+2
                    while receiver.decoded<i+1 and time.monotonic()<limit:time.sleep(.005)
                    self.assertEqual(receiver.decoded,i+1,receiver.status)
                    self.assertEqual(struct.unpack_from('<II',receiver.frames.memory,8),(96,64))
                    pixels=bytes(receiver.frames.memory[64:64+64*96*4])
                    self.assertNotEqual(pixels,previous)
                    previous=pixels
                    advance.set()
            finally:
                done.set();advance.set();receiver.close()
        thread.join(4);self.assertEqual(errors,[])

    @unittest.skipUnless(os.environ.get('FRAMEPHONE_FFMPEG') or shutil.which('ffmpeg'),'FFmpeg integration runs in native CI/package checks')
    def test_encrypted_h264_decodes_and_publishes_without_screenshot_files(self):
        command,env,_=decoder_base()
        clip=subprocess.check_output([*command,'-hide_banner','-loglevel','error','-filter_threads','1','-threads','1','-f','lavfi','-i',
            'testsrc=size=64x96:rate=30','-frames:v','1','-c:v','libx264','-preset','ultrafast',
            '-tune','zerolatency','-g','1','-pix_fmt','yuv420p','-f','h264','pipe:1'],env=env)
        done=threading.Event()
        def send(peer):
            self.assertEqual(read_message(peer)['token'],'a'*64)
            write_message(peer,{'type':'video_ready','version':1,'session':'test','codec':'h264',
                                'generation':'one','width':64,'height':96,'rotation':0})
            for data,flags in ((clip[:64],1),(clip[64:],2)):
                wire=struct.pack('!IIQ',len(data),flags,1)+data
                for start in range(0,len(wire),79):peer.sendall(wire[start:start+79])
            while not done.wait(.1):peer.sendall(struct.pack('!IIQ',0,4,1))
        port,thread,errors=self.server(send)
        with tempfile.TemporaryDirectory() as folder:
            metadata=Path(folder)/'screen.json'
            receiver=self.receiver(port,metadata)
            try:
                limit=time.monotonic()+4
                while receiver.decoded<1 and time.monotonic()<limit:time.sleep(.01)
                self.assertEqual(receiver.decoded,1,
                                 'one complete frame must display without a second frame or EOF: '+receiver.status)
                w,h=struct.unpack_from('<II',receiver.frames.memory,8)
                self.assertEqual((w,h),(64,96))
                time.sleep(.7)
                self.assertLess(time.monotonic_ns()-struct.unpack_from('<Q',receiver.frames.memory,24)[0],300_000_000,
                                'a static authorized screen must stay valid without new frames')
                self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),['screen.json'])
                self.assertNotEqual(bytes(receiver.frames.memory[64:64+64*96*4]),bytes(64*96*4))
            finally:
                done.set();receiver.close()
            self.assertFalse(receiver.thread.is_alive())
            self.assertFalse(metadata.exists())
        thread.join(4);self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()

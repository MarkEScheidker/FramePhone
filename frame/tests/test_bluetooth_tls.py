"""The replacement protocol: real TLS records, two-sided consent, reconnect and Forget."""
import json
from pathlib import Path
import ssl
import struct
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from bluetooth_link import BluetoothLink
from bluetooth_protocol import ControlFragments
from bluetooth_tls import TlsStream, verification_code
from phone_link import PairingStore, PhoneLink
import test_phone_link as fixtures
import time

ADDRESS = '11:22:33:44:55:66'
DEVICE = '/org/bluez/hci0/dev_phone'
CREDENTIAL = 'b'*64


class Connection:
    def __init__(self, link, credential=None, standalone=False):
        self.link, self.credential = link, credential
        self.standalone = standalone
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(fixtures.TLSTests.root/'cert.pem'), str(fixtures.TLSTests.root/'key.pem'))
        self.tls = TlsStream(context, server=True)
        self.messages = []
        self.wire = bytearray()
        self.nonce = 'a'*64
        self.code = None
        self.serial = 0

    def send(self, **message):
        self.tls.send_json(message)

    def step(self):
        data = self.link.read(DEVICE, ADDRESS)
        self.wire.extend(data)
        for payload in self.tls.feed(data):
            assert payload[0] == 0
            message = json.loads(payload[1:]); self.messages.append(message)
            if message['op'] == 'hello':
                if message['mode'] == 'pair':
                    self.code = verification_code(fixtures.TLSTests.pin, message['nonce'], self.nonce)
                    self.send(op='verification', nonce=self.nonce)
                elif message['credential'] == self.credential:
                    self.send(op='ready', host='' if self.standalone else '192.168.1.10',
                              standalone_tracking=self.standalone)
                else:
                    self.send(op='pair_required')
            elif message['op'] == 'enrolled':
                self.credential = CREDENTIAL
                self.send(op='ready', host='' if self.standalone else '192.168.1.10',
                          standalone_tracking=self.standalone)
        data = self.tls.take(32768)
        if data:
            self.wire.extend(data)
            self.serial += 1
            # An MTU-23 link splits the TLS handshake into many small writes.
            for offset in range(0, len(data), 14):
                fragment = struct.pack('<HHH', self.serial, offset, len(data))+data[offset:offset+14]
                self.link.receive(DEVICE, ADDRESS, fragment)
        self.link.poll()

    def until(self, predicate):
        for _ in range(300):
            self.step()
            if predicate(): return
        raise AssertionError(self.link.status)

    def approve(self):
        request = self.link.pairing
        request['accepted'] = True; request['event'].set()
        self.send(op='confirm', accepted=True)
        self.until(lambda: any(m['op'] == 'confirm' for m in self.messages))
        self.send(op='paired', credential=CREDENTIAL)
        self.until(lambda: self.link.peer.authenticated)


class BluetoothTlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixtures.TLSTests.setUpClass()
    @classmethod
    def tearDownClass(cls): fixtures.TLSTests.tearDownClass()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.events = []
        self.store = PairingStore(Path(self.temp.name)/'pairing.json')
        self.link = BluetoothLink(self.store, lambda *event: self.events.append(event))
    def tearDown(self): self.temp.cleanup()

    def enroll(self, standalone=False):
        connection = Connection(self.link, standalone=standalone)
        connection.until(lambda: self.link.pairing is not None)
        self.assertEqual(connection.code, self.link.pairing['code'])
        self.assertIsNone(self.store.load())
        connection.approve()
        return connection

    def test_shared_android_hash_vector(self):
        self.assertEqual(verification_code('a'*64, 'b'*64, 'c'*64), 'F204 0086 70A3 419F ED01 B16D FA26 377D')

    def test_two_approvals_before_credentials_and_routes(self):
        connection = Connection(self.link)
        connection.until(lambda: self.link.pairing is not None)
        self.assertEqual(connection.code, self.link.pairing['code'])
        connection.send(op='confirm', accepted=True)
        connection.step()
        self.assertIsNone(self.store.load())
        self.assertFalse(any(kind == 'bluetooth_endpoint' for kind, _ in self.events))
        connection.approve()
        self.assertEqual(self.store.load()['credential'], CREDENTIAL)
        self.assertEqual(self.store.load()['bluetooth_version'], 2)
        self.assertEqual(self.events[-1], ('bluetooth_endpoint', '192.168.1.10'))
        self.assertNotIn(CREDENTIAL.encode(), connection.wire)
        self.assertNotIn(b'192.168.1.10', connection.wire)

    def test_one_sided_approval_cannot_complete_enrollment(self):
        connection = Connection(self.link)
        connection.until(lambda: self.link.pairing is not None)
        connection.send(op='paired', credential=CREDENTIAL)
        with self.assertRaises(ValueError): connection.step()
        self.assertIsNone(self.store.load())

    def test_hash_stays_visible_if_headset_approves_first_and_can_still_reject(self):
        connection = Connection(self.link)
        connection.until(lambda: self.link.pairing is not None)
        request = self.link.pairing
        request['accepted'] = True; request['event'].set()
        connection.until(lambda: any(m['op'] == 'confirm' for m in connection.messages))
        self.assertIs(self.link.pairing, request)
        self.assertIsNone(self.store.load())
        request['accepted'] = False
        connection.send(op='confirm', accepted=True)
        connection.send(op='paired', credential=CREDENTIAL)
        with self.assertRaises(ValueError): connection.step()
        self.assertIsNone(self.store.load())

    def test_credentials_cannot_be_replaced_twice_in_one_exchange(self):
        connection = self.enroll()
        saved = self.store.load()
        connection.send(op='paired', credential='e'*64)
        with self.assertRaises(ValueError): connection.step()
        self.assertEqual(self.store.load(), saved)

    def test_reconnect_uses_saved_tls_pin_and_credential_without_hash(self):
        self.enroll()
        self.link.disconnected(DEVICE)
        connection = Connection(self.link, CREDENTIAL)
        connection.until(lambda: self.link.peer.authenticated)
        self.assertIsNone(connection.code)
        self.assertIsNone(self.link.pairing)

    def test_forgetting_either_end_requires_new_verification_but_not_new_bond(self):
        self.enroll()
        self.link.disconnected(DEVICE)
        # Phone forgot its credential, but retains the same TLS certificate and radio bond.
        phone_reset = Connection(self.link)
        phone_reset.until(lambda: self.link.pairing is not None)
        self.assertIsNotNone(phone_reset.code)
        self.assertFalse(self.link.peer.authenticated)
        self.link.forget()
        # Frame forgot instead; the remembered phone credential is not enough to enroll.
        frame_reset = Connection(self.link, CREDENTIAL)
        frame_reset.until(lambda: self.link.pairing is not None)
        self.assertIsNotNone(frame_reset.code)
        self.assertIsNone(self.store.load())

    def test_reject_preserves_existing_trust(self):
        self.enroll(); saved = self.store.load()
        self.link.disconnected(DEVICE)
        connection = Connection(self.link)
        connection.until(lambda: self.link.pairing is not None)
        request = self.link.pairing
        request['accepted'] = False; request['event'].set()
        connection.until(lambda: any(m.get('op') == 'confirm' for m in connection.messages))
        self.assertEqual(self.store.load(), saved)
        self.assertFalse(self.link.peer.authenticated)

    def test_phone_rejection_is_acknowledged_without_restarting_pairing(self):
        connection = Connection(self.link)
        connection.until(lambda: self.link.pairing is not None)
        connection.send(op='confirm', accepted=False)
        connection.step()
        self.assertIsNone(self.link.pairing)
        self.assertEqual(self.link.peer.mode, 'declined')
        self.assertIsNone(self.store.load())

    def test_another_phone_is_blocked_until_frame_forgets(self):
        self.enroll()
        self.link.disconnected('an unrelated controller')
        self.assertTrue(self.link.peer.authenticated)
        self.link.disconnected(DEVICE)
        self.assertFalse(self.link.allowed('22:33:44:55:66:77'))
        with self.assertRaises(ValueError): self.link.read('other', '22:33:44:55:66:77')
        self.link.forget()
        self.assertTrue(self.link.allowed('22:33:44:55:66:77'))

    def test_corrupt_tls_record_is_rejected(self):
        connection = self.enroll()
        connection.tls.send_json(dict(op='route', host='192.168.1.11'))
        data = bytearray(connection.tls.take(32768)); data[-1] ^= 1
        with self.assertRaises(ssl.SSLError): self.link.receive(DEVICE, ADDRESS, data, fragmented=False)

    def test_unverified_binary_data_is_rejected(self):
        connection = Connection(self.link)
        connection.until(lambda: self.link.pairing is not None)
        connection.tls.send(b'\1'+bytes(116))
        with self.assertRaises(ValueError): connection.step()

    def test_tls_certificate_is_checked_before_reconnect_credentials(self):
        saved = dict(pin='d'*64, credential=CREDENTIAL, bluetooth_version=2, bluetooth_address=ADDRESS)
        self.store.save(saved)
        connection = Connection(self.link, CREDENTIAL)
        connection.until(lambda: self.link.pairing is not None)
        hello = next(m for m in connection.messages if m['op'] == 'hello')
        self.assertEqual(hello['mode'], 'pair')
        self.assertNotIn('credential', hello)
        self.assertEqual(self.store.load(), saved)
        connection.send(op='ready', host='192.168.1.10')
        with self.assertRaises(ValueError): connection.step()

    def test_encrypted_motion_requires_the_authenticated_wifi_session(self):
        connection = self.enroll()
        session = str(uuid.UUID(int=1)); received = []
        connection.send(op='bind', session=session)
        connection.until(lambda: any(m['op'] == 'bound' for m in connection.messages))
        self.assertIsNone(self.link.peer.bound_session)
        self.link.authorize(session, lambda *values: received.append(values))
        connection.send(op='bind', session=session)
        connection.until(lambda: self.link.peer.bound_session == session)
        self.assertTrue(next(m for m in reversed(connection.messages) if m['op'] == 'bound')['gyro_stream'])
        packet = struct.pack('<4sBBBB16s16s16sQQQQ7f', b'FPBT', 1, 0, 0, 0,
            uuid.UUID(session).bytes, uuid.UUID(int=2).bytes, uuid.UUID(int=3).bytes,
            1, 1000, 900, 0, 0, 0, -.4, 0, 0, 0, 1)
        connection.tls.send(b'\1'+packet)
        connection.until(lambda: bool(received))
        self.assertEqual(received[0][0]['seq'], 1)
        self.assertAlmostEqual(received[0][0]['translation_m'][2], -.4)
        gyro = struct.pack('<4sB16s16s16sBQ3f', b'FPIM', 1, uuid.UUID(session).bytes,
                           uuid.UUID(int=2).bytes, uuid.UUID(int=3).bytes, 1, 1010, .1, .2, .3)
        connection.tls.send(b'\2'+gyro)
        connection.until(lambda: len(received) == 2)
        self.assertEqual(received[1][0]['type'], 'gyro_samples')
        self.assertEqual(received[1][1][0]['t_ns'], 1010)
        self.assertNotIn(gyro, connection.wire)
        wrong_session = bytearray(gyro)
        wrong_session[5:21] = uuid.UUID(int=5).bytes
        connection.tls.send(b'\2'+wrong_session)
        with self.assertRaises(ValueError): connection.step()

    def test_gyro_packet_validation(self):
        from bluetooth_protocol import decode_gyro
        ids = uuid.UUID(int=1).bytes*3
        packet = struct.pack('<4sB16s16s16sBQ3f', b'FPIM', 1, ids[:16], ids[16:32], ids[32:], 1, 9, 0, 0, 1)
        self.assertEqual(decode_gyro(packet)[1][0]['t_ns'], 9)
        for bad in (packet[:-1], packet[:4]+b'\2'+packet[5:],
                    packet[:-4]+struct.pack('<f', float('nan'))):
            with self.assertRaises(ValueError): decode_gyro(bad)

    def test_tracking_session_operates_without_a_wifi_socket(self):
        connection = self.enroll(standalone=True)
        session = str(uuid.UUID(int=7))
        fiducial = dict(family='tag36h11', id=0, black_edge_m=.06, origin='black_square_center',
                        axes='right_up_front', size_source='android_display_dpi',
                        screen_width_px=1080, screen_height_px=2400, black_edge_px=864)
        profile = dict(fixtures.profile(), session=session, arcore_pose_v1=True, fiducial=fiducial,
                       headset_presence_v1=True, automatic_marker_v1=True)
        self.assertFalse(any(kind == 'bluetooth_endpoint' for kind, _ in self.events))
        connection.send(op='tracking_profile', profile=profile)
        connection.until(lambda: any(kind == 'bluetooth_tracking_profile' for kind, _ in self.events))
        phone = PhoneLink(self.store, lambda *_: None, lambda *_: False, bluetooth=self.link)
        phone.start_bluetooth(profile)
        connection.send(op='bind', session=session)
        connection.until(lambda: self.link.peer.bound_session == session)
        now = time.monotonic_ns()
        phone.headset_presence(True, now)
        phone.pump_bluetooth()
        connection.until(lambda: any(m.get('op') == 'tracking' and m['message']['type'] == 'ping'
                                     for m in connection.messages))
        ping = next(m['message'] for m in connection.messages
                    if m.get('op') == 'tracking' and m['message']['type'] == 'ping')
        connection.send(op='tracking', message=dict(type='pong', session=session, h0=ping['h0'],
                                                   p1=ping['h0'], p2=ping['h0']))
        connection.send(op='tracking', message=dict(type='marker_state', session=session, displayed=True,
                                                   fiducial=fiducial))
        connection.until(lambda: phone.telemetry.marker_state_ns is not None and phone.telemetry.rtt_ns is not None)
        self.assertTrue(phone.snapshot()['marker_state_fresh'])
        self.assertTrue(phone.snapshot()['marker_displayed'])
        stamp = time.monotonic_ns()
        packet = struct.pack('<4sBBBB16s16s16sQQQQ7f', b'FPBT', 1, 0, 0, 0,
            uuid.UUID(session).bytes, uuid.UUID(int=2).bytes, uuid.UUID(int=3).bytes,
            1, stamp, stamp, 0, 0, 0, -.4, 0, 0, 0, 1)
        connection.tls.send(b'\1'+packet)
        connection.until(lambda: bool(phone.telemetry.arcore_poses))
        self.assertIsNone(phone.sock)
        self.assertTrue(phone.pose_packet()['clock_valid'])
        self.assertTrue(phone.alignment_command('alignment_accepted', str(uuid.UUID(int=2)), str(uuid.UUID(int=3))))
        phone.pump_bluetooth()
        connection.until(lambda: any(m.get('op') == 'tracking' and m['message']['type'] == 'alignment_accepted'
                                     for m in connection.messages))
        self.link.disconnected(DEVICE)
        self.assertTrue(any(kind == 'bluetooth_tracking_lost' for kind, _ in self.events))
        phone.stop()

    def test_fragment_bounds_and_order(self):
        fragments = ControlFragments()
        self.assertIsNone(fragments.receive('phone', struct.pack('<HHH', 1, 0, 4)+b'ab', 0))
        self.assertEqual(fragments.receive('phone', struct.pack('<HHH', 1, 2, 4)+b'cd', 0), b'abcd')
        self.assertIsNone(fragments.receive('phone', struct.pack('<HHH', 2, 0, 6)+b'ab', 0))
        self.assertIsNone(fragments.receive('phone', struct.pack('<HHH', 2, 2, 6)+b'cd', 2))
        self.assertEqual(fragments.receive('phone', struct.pack('<HHH', 2, 4, 6)+b'ef', 4), b'abcdef')
        with self.assertRaises(ValueError): fragments.receive('phone', struct.pack('<HHH', 1, 0, 32769)+b'a')
        with self.assertRaises(ValueError): fragments.receive('phone', struct.pack('<HHH', 1, 2, 4)+b'cd')


if __name__ == '__main__': unittest.main()

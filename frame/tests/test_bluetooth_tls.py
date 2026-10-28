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
from phone_link import PairingStore
import test_phone_link as fixtures

ADDRESS = '11:22:33:44:55:66'
DEVICE = '/org/bluez/hci0/dev_phone'
CREDENTIAL = 'b'*64


class Connection:
    def __init__(self, link, credential=None):
        self.link, self.credential = link, credential
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
                    self.send(op='ready', host='192.168.1.10')
                else:
                    self.send(op='pair_required')
            elif message['op'] == 'enrolled':
                self.credential = CREDENTIAL
                self.send(op='ready', host='192.168.1.10')
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

    def enroll(self):
        connection = Connection(self.link)
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
        packet = struct.pack('<4sBBBB16s16s16sQQQQ7f', b'FPBT', 1, 0, 0, 0,
            uuid.UUID(session).bytes, uuid.UUID(int=2).bytes, uuid.UUID(int=3).bytes,
            1, 1000, 900, 0, 0, 0, -.4, 0, 0, 0, 1)
        connection.tls.send(b'\1'+packet)
        connection.until(lambda: bool(received))
        self.assertEqual(received[0][0]['seq'], 1)
        self.assertAlmostEqual(received[0][0]['translation_m'][2], -.4)

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

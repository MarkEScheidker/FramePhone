"""BLE binary, trust, framing and renderer-source contracts without a radio."""
import hashlib
import hmac
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from bluetooth_protocol import bootstrap, transcript, decode_pose, ControlFragments
from bluetooth_link import BluetoothLink, PairingApprovalRequired
from phone_link import PairingStore, PhoneLink, Telemetry
from test_phone_link import profile
from test_arcore_link import pose_message

GOLDEN = bytes.fromhex('4650425401030001000000000000000000000000000000010000000000000000000000000000000200000000000000000000000000000003110000000000000000ca9a3b000000008033023b00000000009d693a00000000cdcccc3dcdcc4c3e9a9919bf0000000000000000000000000000803f400caa3b00000000cdcccc3dcdcc4c3e9a99993e')


def fragments(value, count=19):
    raw = json.dumps(value, separators=(',', ':')).encode()
    return [struct.pack('<HHH', 42, offset, len(raw))+raw[offset:offset+count]
            for offset in range(0, len(raw), count)]


def hello(challenge='a'*64, credential='b'*64, pin='c'*64, host='192.168.1.10', address='AA:BB:CC:DD:EE:FF'):
    key = hashlib.sha256(credential.encode()).digest()
    return dict(op='bootstrap', challenge=challenge, pin=pin, host=host, credential=credential,
                proof=hmac.new(key, transcript(challenge, address, pin, host), hashlib.sha256).hexdigest())


class BluetoothTests(unittest.TestCase):
    def test_pairing_is_open_only_until_a_phone_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PairingStore(Path(directory)/'pair.json')
            link=BluetoothLink(store,lambda *v:None)
            phone='11:22:33:44:55:66';other='22:33:44:55:66:77'
            self.assertTrue(link.pairing_allowed(phone))
            self.assertFalse(link.pairing_allowed('unknown'))
            store.save(dict(pin='c'*64,credential='b'*64,bluetooth_address=phone))
            restarted=BluetoothLink(store,lambda *v:None)
            self.assertTrue(restarted.pairing_allowed(phone))
            self.assertFalse(restarted.pairing_allowed(other))
            with self.assertRaises(ValueError):restarted.display_confirmation('other',12345,other)
            restarted.forget()
            self.assertTrue(restarted.pairing_allowed(other))

    def test_number_display_does_not_wait_for_a_headset_click(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:events.append(v))
            link.display_confirmation('phone',12345,'11:22:33:44:55:66')
            request=link.pairing
            self.assertEqual(request['passkey'],'012345')
            self.assertTrue(request['automatic'])
            self.assertFalse(request['event'].is_set())
            self.assertIn('phone',link.bond_approvals)
            with self.assertRaises(ValueError):
                link.display_confirmation('other',12345,'22:33:44:55:66:77')
            self.assertIs(link.pairing,request)
            link.cancel_pairing()
            self.assertIsNone(link.pairing)
            self.assertNotIn('phone',link.bond_approvals)

    def test_completed_bond_hides_the_code_but_allows_secure_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            link.address='AA:BB:CC:DD:EE:FF';device='phone'
            link.device_addresses[device]='11:22:33:44:55:66'
            link.display_confirmation(device,12345,link.device_addresses[device])
            link.finish_display(device)
            self.assertIsNone(link.pairing)
            with self.assertRaises(ValueError):
                link.display_confirmation('other',54321,'22:33:44:55:66:77')
            challenge=json.loads(link.read_control(device))['challenge']
            for part in fragments(hello(challenge=challenge)):link.control(device,part)
            self.assertEqual(link.store.load()['bluetooth_address'],'11:22:33:44:55:66')
            self.assertNotIn(device,link.bond_approvals)

    def test_existing_keys_migrate_the_radio_identity_without_new_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            saved=dict(pin='c'*64,credential='b'*64,host='192.168.1.10')
            link.store.save(saved);link.address='AA:BB:CC:DD:EE:FF';device='phone'
            phone='11:22:33:44:55:66';link.device_addresses[device]=phone
            self.assertFalse(link.pairing_allowed(phone)) # identity not learned yet
            challenge=json.loads(link.read_control(device))['challenge']
            request=hello(challenge=challenge);request.pop('credential')
            for part in fragments(request):link.control(device,part)
            self.assertTrue(link.pairing_allowed(phone))
            self.assertEqual(link.store.load()['credential'],saved['credential'])

    def test_an_existing_bond_cannot_replace_a_different_saved_phone(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            saved=dict(pin='c'*64,credential='b'*64,bluetooth_address='11:22:33:44:55:66')
            link.store.save(saved);link.address='AA:BB:CC:DD:EE:FF'
            link.device_addresses['other']='22:33:44:55:66:77'
            challenge=json.loads(link.read_control('other'))['challenge']
            for part in fragments(hello(challenge=challenge,pin='d'*64,credential='e'*64)):
                link.control('other',part)
            self.assertEqual(json.loads(link.read_control('other'))['code'],'headset_paired')
            self.assertIsNone(link.pairing)
            self.assertEqual(link.store.load(),saved)
            with self.assertRaises(ValueError):link.commit_bootstrap('other',saved,saved,replace=True)

    def test_unreadable_pairing_never_opens_radio_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PairingStore(Path(directory)/'pair.json')
            store.save(dict(pin='c'*64,credential='b'*64))
            store.path.write_text('{broken')
            link=BluetoothLink(store,lambda *v:None)
            with self.assertRaises(ValueError):link.display_confirmation('phone',12345,'11:22:33:44:55:66')
            self.assertIsNone(link.pairing)
            self.assertFalse(link.bond_approvals)

    def test_cross_language_binary_contract(self):
        pose, gyro = decode_pose(GOLDEN)
        self.assertEqual(pose['session'], str(uuid.UUID(int=1)))
        self.assertEqual(pose['generation'], str(uuid.UUID(int=2)))
        self.assertEqual(pose['acquisition'], str(uuid.UUID(int=3)))
        self.assertEqual((pose['seq'],pose['t_ns'],pose['capture_t_ns']), (17,1_000_000_000,980_000_000))
        self.assertAlmostEqual(pose['translation_m'][2], -.6, places=6)
        self.assertAlmostEqual(gyro[0]['w_rad_s'][2], .3, places=6)
        self.assertEqual(gyro[0]['t_ns'],1_001_000_000)
        state = Telemetry(dict(profile(), session=pose['session'], arcore_pose_v1=True))
        state.receive(pose,2_000_000_000)
        self.assertEqual(state.arcore_poses[-1]['seq'],17)

    def test_phone_pause_reason_survives_ble(self):
        paused=bytearray(GOLDEN);paused[6]=0x21
        message,_=decode_pose(paused)
        self.assertEqual((message['state'],message['reason']),('paused','user_dismissed'))

    def test_malformed_binary_rejected(self):
        for blob in (b'', GOLDEN[:-1], GOLDEN+b'x', bytes(600), b'FAIL'+GOLDEN[4:]):
            with self.subTest(size=len(blob)), self.assertRaises(ValueError): decode_pose(blob)
        for offset, value in ((4,2),(5,128),(6,99),(7,255)):
            damaged=bytearray(GOLDEN);damaged[offset]=value
            with self.assertRaises(ValueError): decode_pose(damaged)
        bad=bytearray(GOLDEN);struct.pack_into('<f',bad,88,float('nan'))
        with self.assertRaises(ValueError): decode_pose(bad)
        bad=bytearray(GOLDEN);struct.pack_into('<Q',bad,80,2_000_000_000)
        with self.assertRaises(ValueError): decode_pose(bad)

    def test_bluetooth_first_enrollment_and_existing_pair_migration(self):
        result=bootstrap(hello(),'a'*64,'AA:BB:CC:DD:EE:FF',None,True)
        self.assertEqual(result['credential'],'b'*64)
        reconnect=hello();reconnect.pop('credential')
        self.assertEqual(bootstrap(reconnect,'a'*64,'AA:BB:CC:DD:EE:FF',result,False),result)
        for changed in (dict(reconnect,pin='d'*64),dict(reconnect,proof='0'*64),dict(reconnect,challenge='d'*64)):
            with self.assertRaises(ValueError): bootstrap(changed,'a'*64,'AA:BB:CC:DD:EE:FF',result,True)
        with self.assertRaises(ValueError): bootstrap(hello(),'a'*64,'AA:BB:CC:DD:EE:FF',None,False)
        with self.assertRaises(ValueError): bootstrap(hello(host='127.0.0.1'),'a'*64,'AA:BB:CC:DD:EE:FF',None,True)

    def test_control_fragmentation_bounded_and_expiring(self):
        decoder=ControlFragments(); message=hello(); parts=fragments(message)
        for part in parts[:-1]: self.assertIsNone(decoder.receive('phone',part,0))
        self.assertEqual(decoder.receive('phone',parts[-1],0),message)
        decoder.receive('phone',parts[0],0)
        with self.assertRaises(ValueError): decoder.receive('phone',parts[1],4)
        with self.assertRaises(ValueError): decoder.receive('phone',struct.pack('<HHH',1,0,1025)+b'x',5)
        with self.assertRaises(ValueError): decoder.receive('phone',parts[1],5)

    def test_bootstrap_session_proof_and_no_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:events.append(v))
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.bond_approvals[device]=time.monotonic()+120
            challenge=json.loads(link.read_control(device))['challenge']
            for part in fragments(hello(challenge=challenge)):link.control(device,part)
            self.assertEqual(events,[('bluetooth_endpoint','192.168.1.10')])
            self.assertTrue(link.store.load()['bluetooth'])
            ready=json.loads(link.read_control(device)); session=str(uuid.UUID(int=1))
            message=dict(op='bind',binding=ready['binding'],session=session,
                proof=hmac.new(bytes.fromhex(ready['token']),session.encode(),hashlib.sha256).hexdigest())
            received=[];link.authorize(session,lambda *v:received.append(v))
            for part in fragments(message):link.control(device,part)
            link.pose(device,GOLDEN)
            self.assertEqual(received[0][0]['seq'],17)
            with self.assertRaises(ValueError):link.pose('/another/device',GOLDEN)
            with self.assertRaises(ValueError):
                for part in fragments(hello(challenge=challenge)):link.control(device,part)
            link.revoke(session)
            with self.assertRaises(ValueError):link.pose(device,GOLDEN)

    def test_forget_revokes_radio_state_and_application_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.bond_approvals[device]=time.monotonic()+120
            challenge=json.loads(link.read_control(device))['challenge']
            for part in fragments(hello(challenge=challenge)):link.control(device,part)
            link.authorize(str(uuid.UUID(int=1)),lambda *v:None)
            link.forget()
            self.assertIsNone(link.store.load())
            self.assertIsNone(link.expected)
            self.assertIsNone(link.peer)
            self.assertEqual(json.loads(link.read_control(device))['op'],'challenge')
            with self.assertRaises(ValueError):link.pose(device,GOLDEN)

    def test_route_refresh_before_tls_session(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:events.append(v))
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.bond_approvals[device]=time.monotonic()+120
            challenge=json.loads(link.read_control(device))['challenge']
            for part in fragments(hello(challenge=challenge)):link.control(device,part)
            ready=json.loads(link.read_control(device))
            # An initial TLS attempt may fail before it can authorize/revoke a
            # session. The live BLE link must still be able to refresh its route.
            request=hello(challenge=ready['challenge'],host='192.168.1.20')
            request.pop('credential')
            for part in fragments(request):link.control(device,part)
            self.assertEqual(link.store.load()['host'],'192.168.1.20')
            self.assertEqual(events[-1],('bluetooth_endpoint','192.168.1.20'))
            self.assertNotEqual(json.loads(link.read_control(device))['binding'],ready['binding'])

    def test_unreadable_saved_pairing_reports_app_recovery_not_radio_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store=PairingStore(Path(directory)/'pair.json')
            store.save(dict(pin='c'*64,credential='b'*64,host='192.168.1.10'))
            store.path.write_text('{broken')
            link=BluetoothLink(store,lambda *v:None);link.address='AA:BB:CC:DD:EE:FF'
            self.assertEqual(json.loads(link.read_control('/org/bluez/hci0/dev_phone'))['code'],'saved_pairing_invalid')
            link.forget()
            self.assertFalse(json.loads(link.read_control('/org/bluez/hci0/dev_phone'))['paired'])

    def test_small_mtu_reads_keep_one_snapshot_including_error_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            for error in (None,'pairing_rejected'):
                if error:link.setup_errors[device]=error
                complete=link.read_control(device)
                rebuilt=complete[:22]
                for offset in range(22,len(complete),22):rebuilt+=link.read_control(device,offset)[:22]
                self.assertEqual(rebuilt,complete)
                self.assertEqual(json.loads(rebuilt)['op'],'error' if error else 'challenge')
            with self.assertRaises(ValueError):link.read_control(device,len(complete)+1)

    def test_existing_os_bond_without_app_record_requires_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            challenge=json.loads(link.read_control(device))
            self.assertFalse(challenge['paired'])
            with self.assertRaises(PairingApprovalRequired) as proposal:
                for part in fragments(hello(challenge=challenge['challenge'])):link.control(device,part)
            self.assertIsNone(link.store.load())
            link.commit_bootstrap(device,proposal.exception.candidate,None,replace=True)
            self.assertEqual(link.store.load()['credential'],'b'*64)

    def test_reinstalled_phone_requires_replacement_then_old_binding_is_revoked(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:events.append(v))
            old=dict(bluetooth_address='11:22:33:44:55:66',pin='c'*64,credential='b'*64,host='192.168.1.10')
            link.store.save(old);link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.device_addresses[device]='11:22:33:44:55:66'
            old_session=str(uuid.UUID(int=1));link.authorize(old_session,lambda *v:None)
            challenge=json.loads(link.read_control(device))['challenge']
            with self.assertRaises(PairingApprovalRequired) as proposal:
                for part in fragments(hello(challenge=challenge,pin='d'*64,credential='e'*64)):link.control(device,part)
            self.assertEqual(link.store.load(),old,'proposal/rejection changed the old trust record')
            link.commit_bootstrap(device,proposal.exception.candidate,proposal.exception.previous,replace=True)
            self.assertEqual(link.store.load()['pin'],'d'*64)
            self.assertIsNone(link.expected)
            new_binding=link.peer.copy()
            link.revoke(old_session) # Old TLS shutdown must not erase the replacement.
            self.assertEqual(link.peer,new_binding)
            self.assertEqual([kind for kind,_ in events],['bluetooth_replaced','bluetooth_endpoint'])

    def test_desynchronized_credentials_offer_recovery_without_destroying_saved_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            saved=dict(bluetooth_address='11:22:33:44:55:66',pin='c'*64,credential='b'*64,host='192.168.1.10')
            link.store.save(saved);link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.device_addresses[device]='11:22:33:44:55:66'
            challenge=json.loads(link.read_control(device))['challenge']
            wrong=hello(challenge=challenge,credential='e'*64);wrong.pop('credential')
            for part in fragments(wrong):link.control(device,part)
            self.assertEqual(json.loads(link.read_control(device))['code'],'pairing_mismatch')
            self.assertEqual(link.store.load(),saved)
            challenge=json.loads(link.read_control(device))['challenge']
            with self.assertRaises(PairingApprovalRequired):
                for part in fragments(hello(challenge=challenge,credential='e'*64)):link.control(device,part)

    def test_forget_does_not_silently_reenroll_an_existing_bond(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.bond_approvals[device]=time.monotonic()+120
            link.forget()
            challenge=json.loads(link.read_control(device))['challenge']
            with self.assertRaises(PairingApprovalRequired):
                for part in fragments(hello(challenge=challenge)):link.control(device,part)
            self.assertIsNone(link.store.load())

    def test_stale_confirmation_and_lost_ack_cannot_replace_newer_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            link=BluetoothLink(PairingStore(Path(directory)/'pair.json'),lambda *v:None)
            link.address='AA:BB:CC:DD:EE:FF';device='/org/bluez/hci0/dev_phone'
            link.device_addresses[device]='11:22:33:44:55:66'
            original=dict(bluetooth_address='11:22:33:44:55:66',pin='c'*64,credential='b'*64,host='192.168.1.10')
            link.store.save(original)
            challenge=json.loads(link.read_control(device))['challenge']
            with self.assertRaises(PairingApprovalRequired) as proposal:
                for part in fragments(hello(challenge=challenge,credential='e'*64)):link.control(device,part)
            newer=dict(original,credential='f'*64);link.store.save(newer)
            with self.assertRaises(ValueError):
                link.commit_bootstrap(device,proposal.exception.candidate,proposal.exception.previous,replace=True)
            self.assertEqual(link.store.load(),newer)
            # If an approved save succeeded but its ACK was lost, retrying the
            # same pending credential must succeed without a new trust prompt.
            challenge=json.loads(link.read_control(device))['challenge']
            for part in fragments(hello(challenge=challenge,credential='f'*64)):link.control(device,part)
            self.assertEqual(link.store.load()['credential'],'f'*64)

    def test_fresh_ble_preferred_then_wifi_fallback(self):
        link=PhoneLink(None,None,None)
        data=dict(profile(),arcore_pose_v1=True)
        link.telemetry=Telemetry(data);link.ble_telemetry=Telemetry(data)
        probe=dict(session='test-session',h0=1_900_000_000,p1=900_500_000,p2=900_500_000)
        link.telemetry.clock_reply(probe,1_901_000_000,{1_900_000_000})
        now=time.monotonic_ns()
        sample=pose_message(1,now+1_000_000_000)
        link.telemetry.receive(sample,now)
        link.receive_bluetooth(sample,[],now)
        self.assertIs(link._pose_state(now+10_000_000),link.ble_telemetry)
        self.assertIs(link._pose_state(now+150_000_001),link.telemetry)
        # A replay is dropped without erasing the live state or killing TLS.
        link.receive_bluetooth(sample,[],now+1)
        self.assertEqual(len(link.ble_telemetry.arcore_poses),1)
        # Reliable tracking-loss/state traffic may beat an older BLE sample.
        link.telemetry.receive(pose_message(2,now+1_010_000_000),now+10_000_000)
        self.assertIs(link._pose_state(now+20_000_000),link.telemetry)
        link.stopped.set()
        link.receive_bluetooth(pose_message(2,now+2_000_000_000),[],now+2)
        self.assertEqual(len(link.ble_telemetry.arcore_poses),1)


if __name__=='__main__':unittest.main()

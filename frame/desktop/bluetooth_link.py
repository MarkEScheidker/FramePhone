"""No-code Bluetooth bonding, followed by verified TLS enrollment and encrypted poses."""
import asyncio
import hmac
import ipaddress
import json
import os
import re
import threading
import time
import uuid

from bluetooth_protocol import SERVICE, CONTROL, POSE, ControlFragments, decode_pose, decode_gyro
from bluetooth_tls import TlsStream, verification_code


def current_pairing(store):
    saved = store.load()
    return saved if saved and saved.get('bluetooth_version') == 2 else None


class Peer:
    def __init__(self, device, address):
        self.device, self.address = device, address
        self.tls = TlsStream()
        self.authenticated = self.local_approved = self.phone_approved = False
        self.enrolled = False
        self.nonce = ''
        self.mode = None
        self.bound_session = None
        self.standalone = False
        self.snapshot = b''
        self.deadline = time.monotonic()+120


class BluetoothLink:
    def __init__(self, store, notify):
        self.store, self.notify = store, notify
        self.status = 'Bluetooth starting'
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.peer = self.expected = self.pairing = None
        self.fragments = ControlFragments()
        self.candidate = None
        self._disconnect_radio = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='bluetooth', daemon=True)
            self.thread.start()

    def allowed(self, address):
        saved = current_pairing(self.store)
        return not saved or saved.get('bluetooth_address') == address

    def authorize(self, session, receive):
        with self.lock:
            self.expected = session, receive

    def revoke(self, session):
        with self.lock:
            if self.expected and self.expected[0] == session:
                self.expected = None
                if self.peer:
                    self.peer.bound_session = None

    def send_tracking(self, message):
        with self.lock:
            peer = self.peer
            if not peer or not peer.authenticated or not peer.standalone or not self.expected:
                return False
            if message.get('session') != self.expected[0] or peer.bound_session != self.expected[0]:
                return False
            try:
                peer.tls.send_json(dict(op='tracking', message=message))
            except ValueError:
                return False
            return True

    def _clear_prompt(self):
        if self.pairing:
            request, self.pairing = self.pairing, None
            self.notify('bluetooth_pairing_closed', request)

    def forget(self):
        with self.lock:
            device = self.peer.device if self.peer else None
            self._clear_prompt()
            self.store.forget()
            self.peer = self.expected = self.candidate = None
            self.fragments = ControlFragments()
        if self.ready.is_set():
            self.status = 'Bluetooth ready — pair a phone'
        if device and self._disconnect_radio:
            self._disconnect_radio(device)

    def disconnected(self, device):
        with self.lock:
            if not ((self.peer and self.peer.device == device) or (self.candidate and self.candidate[0] == device)):
                return
            if self.peer and self.peer.device == device:
                if self.peer.standalone:
                    self.notify('bluetooth_tracking_lost', None)
                self._clear_prompt()
                self.peer = None
            self.fragments.pending.pop(device, None)
            if self.candidate and self.candidate[0] == device:
                self.candidate = None
        if self.ready.is_set():
            self.status = 'Bluetooth ready — waiting for phone'

    def _peer(self, device, address):
        if not self.allowed(address):
            raise ValueError('Forget the remembered phone before connecting another phone')
        if self.peer is None:
            self.peer = Peer(device, address)
        if self.peer.device != device:
            raise ValueError('Another phone is connecting')
        return self.peer

    def read(self, device, address, offset=0):
        with self.lock:
            peer = self._peer(device, address)
            if not offset:
                peer.snapshot = peer.tls.take()
            if not 0 <= offset <= len(peer.snapshot):
                raise ValueError('Invalid Bluetooth read offset')
            return peer.snapshot[offset:]

    def receive(self, device, address, value, fragmented=True):
        with self.lock:
            peer = self._peer(device, address)
            data = self.fragments.receive(device, value) if fragmented else value
            if data is None:
                return
            messages = peer.tls.feed(data)
            if peer.tls.ready and peer.mode is None:
                saved = current_pairing(self.store)
                # A stored pin is checked before its credential ever enters TLS.
                if saved and hmac.compare_digest(saved['pin'], peer.tls.pin):
                    peer.mode = 'reconnect'
                    peer.tls.send_json(dict(op='hello', version=2, mode='reconnect', credential=saved['credential'], standalone_tracking=True))
                else:
                    self._begin_pairing(peer)
            for message in messages:
                if not message:
                    raise ValueError('Empty Bluetooth TLS message')
                if message[0] in (1, 2):
                    if not peer.authenticated or not self.expected or peer.bound_session != self.expected[0]:
                        raise ValueError('Unverified Bluetooth pose')
                    pose, gyro = (decode_pose if message[0] == 1 else decode_gyro)(message[1:])
                    if pose['session'] != peer.bound_session:
                        raise ValueError('Bluetooth pose belongs to another session')
                    self.expected[1](pose, gyro, time.monotonic_ns())
                elif message[0] == 0:
                    self._message(peer, json.loads(message[1:]))
                else:
                    raise ValueError('Unknown Bluetooth TLS message type')

    def _begin_pairing(self, peer):
        peer.authenticated = peer.local_approved = peer.phone_approved = peer.enrolled = False
        peer.bound_session = None
        peer.nonce = os.urandom(32).hex()
        peer.mode = 'pair'
        peer.tls.send_json(dict(op='hello', version=2, mode='pair', nonce=peer.nonce, standalone_tracking=True))

    def _message(self, peer, message):
        if not isinstance(message, dict):
            raise ValueError('Invalid Bluetooth message')
        op = message.get('op')
        if op == 'pair_required' and peer.mode == 'reconnect':
            self._begin_pairing(peer)
        elif op == 'verification' and peer.mode == 'pair' and not peer.enrolled and self.pairing is None:
            code = verification_code(peer.tls.pin, peer.nonce, message.get('nonce'))
            request = dict(device=peer.device, code=code, accepted=False, event=threading.Event())
            self.pairing = request
            self.status = 'Compare the hash on both devices'
            self.notify('bluetooth_pairing', request)
        elif op == 'confirm' and peer.mode == 'pair':
            peer.phone_approved = message.get('accepted') is True
            if not peer.phone_approved:
                self._clear_prompt()
                peer.mode = 'declined'
                self.status = 'Phone declined verification'
        elif (op == 'paired' and peer.mode == 'pair' and peer.local_approved and peer.phone_approved and
              not peer.enrolled and self.pairing and self.pairing['accepted']):
            credential = message.get('credential')
            if not isinstance(credential, str) or not re.fullmatch('[0-9a-f]{64}', credential):
                raise ValueError('Invalid enrollment credential')
            self.store.save(dict(pin=peer.tls.pin, credential=credential, bluetooth_address=peer.address,
                                 bluetooth=True, bluetooth_version=2))
            peer.enrolled = True
            self._clear_prompt()
            self.expected = None
            self.notify('bluetooth_replaced', None)
            peer.tls.send_json(dict(op='enrolled'))
        elif op == 'ready' and peer.mode in ('pair', 'reconnect'):
            if peer.mode == 'pair' and not peer.enrolled:
                raise ValueError('Hash verification is incomplete')
            saved = current_pairing(self.store)
            if not saved or saved['pin'] != peer.tls.pin:
                raise ValueError('Pairing not verified')
            peer.authenticated = True
            peer.standalone = message.get('standalone_tracking') is True
            self.status = 'Bluetooth secure — starting tracking' if peer.standalone else 'Bluetooth secure — waiting for Wi-Fi'
            self._route(peer, message.get('host', ''))
        elif op == 'tracking_profile' and peer.authenticated and peer.standalone:
            profile = message.get('profile')
            if not isinstance(profile, dict):
                raise ValueError('Invalid Bluetooth tracking profile')
            self.notify('bluetooth_tracking_profile', profile)
        elif op == 'tracking' and peer.authenticated and peer.standalone and self.expected:
            data = message.get('message')
            if not isinstance(data, dict) or data.get('session') != self.expected[0] or peer.bound_session != self.expected[0]:
                raise ValueError('Invalid Bluetooth tracking session')
            self.expected[1](data, [], time.monotonic_ns())
        elif op == 'route' and peer.authenticated:
            self._route(peer, message.get('host', ''))
        elif op == 'bind' and peer.authenticated:
            session = str(uuid.UUID(message['session']))
            accepted = bool(self.expected and self.expected[0] == session)
            peer.bound_session = session if accepted else None
            peer.tls.send_json(dict(op='bound', accepted=accepted, session=session, gyro_stream=True))
            if accepted:
                self.status = 'Tracking over encrypted Bluetooth'
        else:
            raise ValueError('Unexpected Bluetooth message')

    def _route(self, peer, host):
        if not host:
            return
        address = ipaddress.IPv4Address(host)
        if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_link_local:
            raise ValueError('Invalid phone LAN route')
        saved = current_pairing(self.store)
        if not saved or saved['pin'] != peer.tls.pin:
            raise ValueError('Pairing changed')
        saved.update(host=host, bluetooth_address=peer.address)
        self.store.save(saved)
        if not peer.standalone:
            self.notify('bluetooth_endpoint', host)

    def poll(self):
        with self.lock:
            peer, request = self.peer, self.pairing
            if peer and not peer.authenticated and time.monotonic() > peer.deadline:
                self.disconnected(peer.device)
                self.status = 'Pairing timed out — connect again'
            elif peer and request and request['event'].is_set() and (not peer.local_approved or not request['accepted']):
                accepted = request['accepted'] and not self.stopped.is_set()
                if not accepted:
                    self._clear_prompt()
                peer.local_approved = accepted
                peer.tls.send_json(dict(op='confirm', accepted=accepted))
                if not accepted:
                    peer.mode = 'declined'
                self.status = 'Waiting for phone approval' if accepted else 'Verification declined'

    def _run(self):
        try:
            asyncio.run(self._supervise())
        except Exception as error:
            self.status = 'Bluetooth unavailable: '+str(error)[:160]

    async def _supervise(self):
        while not self.stopped.is_set():
            self.status = 'Bluetooth starting'
            try:
                await self._serve()
                if not self.stopped.is_set():
                    self.status = 'Bluetooth service lost — reconnecting'
            except Exception as error:
                self.status = 'Bluetooth unavailable: '+str(error)[:160]
            finally:
                self.ready.clear()
            for _ in range(30):
                if self.stopped.is_set():
                    return
                await asyncio.sleep(.1)

    async def _serve(self):
        from dbus_next import BusType, Variant, DBusError, PropertyAccess, Message, MessageType
        from dbus_next.aio import MessageBus
        from dbus_next.service import ServiceInterface, method, dbus_property
        owner = self
        base = '/com/framephone/bluetooth'
        service_path = base+'/service0'
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        managers = []
        released = asyncio.Event()
        adapter = None
        properties = None
        changed_settings = []
        try:
            reply = await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus', member='GetNameOwner', signature='s', body=['org.bluez']))
            if reply.message_type == MessageType.ERROR:
                raise ValueError('BlueZ is not running')
            bluez_owner = reply.body[0]

            def sender_guard(message):
                if (message.message_type == MessageType.METHOD_CALL and message.path and message.path.startswith(base+'/') and
                        message.interface in ('org.bluez.Agent1', 'org.bluez.GattCharacteristic1') and message.sender != bluez_owner):
                    bus.send(Message.new_error(message, 'org.bluez.Error.NotAuthorized', 'BlueZ owns radio access'))
                    return True
                if (message.message_type == MessageType.SIGNAL and message.sender == 'org.freedesktop.DBus' and
                        message.interface == 'org.freedesktop.DBus' and message.member == 'NameOwnerChanged' and
                        message.body[0] == 'org.bluez' and message.body[1] == bluez_owner):
                    released.set()
                if (message.message_type == MessageType.SIGNAL and message.sender == bluez_owner and
                        message.interface == 'org.freedesktop.DBus.Properties' and message.member == 'PropertiesChanged'):
                    values = message.body[1]
                    if message.body[0] == 'org.bluez.Adapter1' and message.path == adapter:
                        if (('Powered' in values and not values['Powered'].value) or
                                ('Pairable' in values and not values['Pairable'].value)):
                            released.set()
                    elif message.body[0] == 'org.bluez.Device1':
                        if 'Connected' in values and not values['Connected'].value:
                            owner.disconnected(message.path)
                        elif not owner.peer and message.path.startswith(adapter+'/dev_'):
                            if 'Paired' in values and values['Paired'].value:
                                owner.status = 'Bluetooth bonded — waiting for secure setup'
                            elif 'Connected' in values and values['Connected'].value:
                                owner.status = 'Bluetooth radio connected — waiting for phone'
            bus.add_message_handler(sender_guard)

            async def device_info(device, paired=False):
                if owner.peer and owner.peer.device == device:
                    return owner.peer.address
                reply = await bus.call(Message(destination=bluez_owner, path=device,
                    interface='org.freedesktop.DBus.Properties', member='GetAll', signature='s', body=['org.bluez.Device1']))
                if reply.message_type == MessageType.ERROR:
                    raise DBusError('org.bluez.Error.Rejected', 'Phone is unavailable')
                values = reply.body[0]
                if paired and not values.get('Paired', Variant('b', False)).value:
                    raise DBusError('org.bluez.Error.NotAuthorized', 'Complete Bluetooth bonding first')
                address = values.get('Address', Variant('s', '')).value.upper()
                if not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', address) or not owner.allowed(address):
                    owner.status = 'Forget the remembered phone to connect another phone'
                    raise DBusError('org.bluez.Error.Rejected', 'Phone is not available for pairing')
                return address

            class Service(ServiceInterface):
                def __init__(self): super().__init__('org.bluez.GattService1')
                @dbus_property(access=PropertyAccess.READ)
                def UUID(self) -> 's': return SERVICE
                @dbus_property(access=PropertyAccess.READ)
                def Primary(self) -> 'b': return True
                @dbus_property(access=PropertyAccess.READ)
                def Includes(self) -> 'ao': return []

            class Characteristic(ServiceInterface):
                def __init__(self, control):
                    super().__init__('org.bluez.GattCharacteristic1'); self.control = control
                @dbus_property(access=PropertyAccess.READ)
                def UUID(self) -> 's': return CONTROL if self.control else POSE
                @dbus_property(access=PropertyAccess.READ)
                def Service(self) -> 'o': return service_path
                @dbus_property(access=PropertyAccess.READ)
                def Flags(self) -> 'as':
                    return ['read', 'write', 'encrypt-read', 'encrypt-write'] if self.control else ['write-without-response', 'encrypt-write']
                @method()
                async def ReadValue(self, options: 'a{sv}') -> 'ay':
                    if not self.control: raise DBusError('org.bluez.Error.NotPermitted', 'Write only')
                    device = options['device'].value
                    address = await device_info(device, paired=True)
                    try: return owner.read(device, address, options.get('offset', Variant('q', 0)).value)
                    except ValueError: raise DBusError('org.bluez.Error.NotAuthorized', 'Bluetooth setup rejected')
                @method()
                async def WriteValue(self, value: 'ay', options: 'a{sv}'):
                    device = options['device'].value
                    address = await device_info(device, paired=True)
                    try: owner.receive(device, address, bytes(value), fragmented=self.control)
                    except Exception as error:
                        owner.disconnected(device)
                        owner.status = f'Secure Bluetooth failed ({type(error).__name__}) — connect again'
                        raise DBusError('org.bluez.Error.NotAuthorized', 'Secure Bluetooth message rejected')

            class Agent(ServiceInterface):
                def __init__(self): super().__init__('org.bluez.Agent1')
                async def admit(self, device):
                    await device_info(device)
                    with owner.lock:
                        if owner.candidate and owner.candidate[0] != device and time.monotonic() < owner.candidate[1]:
                            raise DBusError('org.bluez.Error.Rejected', 'Another phone is connecting')
                        owner.candidate = device, time.monotonic()+120
                    owner.status = 'Bluetooth pairing — approve on the phone if prompted'
                @method()
                async def RequestAuthorization(self, device: 'o'): await self.admit(device)
                @method()
                async def RequestConfirmation(self, device: 'o', passkey: 'u'): await self.admit(device)
                @method()
                def RequestPinCode(self, device: 'o') -> 's': raise DBusError('org.bluez.Error.Rejected', 'PIN pairing unsupported')
                @method()
                def RequestPasskey(self, device: 'o') -> 'u': raise DBusError('org.bluez.Error.Rejected', 'Passkey pairing unsupported')
                @method()
                def DisplayPasskey(self, device: 'o', passkey: 'u', entered: 'q'): pass
                @method()
                def DisplayPinCode(self, device: 'o', pincode: 's'): pass
                @method()
                def AuthorizeService(self, device: 'o', uuid: 's'):
                    if uuid.lower() != SERVICE: raise DBusError('org.bluez.Error.Rejected', 'Unsupported service')
                @method()
                def Cancel(self):
                    if owner.candidate: owner.disconnected(owner.candidate[0])
                @method()
                def Release(self): released.set()

            class Advertisement(ServiceInterface):
                def __init__(self): super().__init__('org.bluez.LEAdvertisement1')
                @dbus_property(access=PropertyAccess.READ)
                def Type(self) -> 's': return 'peripheral'
                @dbus_property(access=PropertyAccess.READ)
                def ServiceUUIDs(self) -> 'as': return [SERVICE]
                @dbus_property(access=PropertyAccess.READ)
                def LocalName(self) -> 's': return 'Steam Frame'
                @method()
                def Release(self): released.set()

            tree = await bus.introspect(bluez_owner, '/')
            objects = await bus.get_proxy_object(bluez_owner, '/', tree).get_interface('org.freedesktop.DBus.ObjectManager').call_get_managed_objects()
            adapter = next((path for path, interfaces in objects.items() if 'org.bluez.GattManager1' in interfaces and
                            'org.bluez.LEAdvertisingManager1' in interfaces and
                            interfaces.get('org.bluez.Adapter1', {}).get('Powered', Variant('b', False)).value), None)
            if not adapter: raise ValueError('Enable headset Bluetooth')
            obj = bus.get_proxy_object(bluez_owner, adapter, await bus.introspect(bluez_owner, adapter))
            daemon = bus.get_proxy_object('org.freedesktop.DBus', '/org/freedesktop/DBus', await bus.introspect('org.freedesktop.DBus', '/org/freedesktop/DBus'))
            await daemon.get_interface('org.freedesktop.DBus').call_add_match(
                "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'")
            await daemon.get_interface('org.freedesktop.DBus').call_add_match(
                "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',path_namespace='"+adapter+"'")
            bus.export(base, ServiceInterface('com.framephone.BluetoothApplication1'))
            bus.export(service_path, Service())
            bus.export(service_path+'/control', Characteristic(True))
            bus.export(service_path+'/pose', Characteristic(False))
            bus.export(base+'/agent', Agent())
            bus.export(base+'/advertisement', Advertisement())
            agent = bus.get_proxy_object(bluez_owner, '/org/bluez', await bus.introspect(bluez_owner, '/org/bluez')).get_interface('org.bluez.AgentManager1')
            await agent.call_register_agent(base+'/agent', 'NoInputNoOutput')
            managers.append((agent.call_unregister_agent, base+'/agent'))
            await agent.call_request_default_agent(base+'/agent')
            # Advertising a service alone does not enable incoming OS bonding.
            # Keep pairing available while our agent applies the saved-phone policy.
            properties = obj.get_interface('org.freedesktop.DBus.Properties')
            for name, desired in (('PairableTimeout', Variant('u', 0)), ('Pairable', Variant('b', True))):
                previous = await properties.call_get('org.bluez.Adapter1', name)
                if previous.value != desired.value:
                    await properties.call_set('org.bluez.Adapter1', name, desired)
                    changed_settings.append((name, previous, desired))
            manager = obj.get_interface('org.bluez.GattManager1')
            await manager.call_register_application(base, {})
            managers.append((manager.call_unregister_application, base))
            advertiser = obj.get_interface('org.bluez.LEAdvertisingManager1')
            await advertiser.call_register_advertisement(base+'/advertisement', {})
            managers.append((advertiser.call_unregister_advertisement, base+'/advertisement'))
            loop = asyncio.get_running_loop()
            async def disconnect(device):
                await bus.call(Message(destination=bluez_owner, path=device, interface='org.bluez.Device1', member='Disconnect'))
            self._disconnect_radio = lambda device: asyncio.run_coroutine_threadsafe(disconnect(device), loop)
            if released.is_set():
                raise ValueError('Bluetooth service was released during startup')
            self.ready.set()
            self.status = 'Bluetooth ready — waiting for remembered phone' if current_pairing(self.store) else 'Bluetooth ready — pair a phone'
            while not self.stopped.is_set() and bus.connected and not released.is_set():
                self.poll()
                await asyncio.sleep(.1)
        finally:
            self.ready.clear()
            if not self.stopped.is_set():
                self.status = 'Bluetooth service lost — reconnecting'
            self._disconnect_radio = None
            with owner.lock:
                owner._clear_prompt()
                if owner.peer and owner.peer.standalone:
                    owner.notify('bluetooth_tracking_lost', None)
                owner.peer = owner.candidate = None
                owner.fragments = ControlFragments()
            for unregister, path in reversed(managers):
                try: await unregister(path)
                except Exception: pass
            for name, previous, desired in reversed(changed_settings):
                try:
                    if (await properties.call_get('org.bluez.Adapter1', name)).value == desired.value:
                        await properties.call_set('org.bluez.Adapter1', name, previous)
                except Exception: pass
            bus.disconnect()

    def close(self):
        self.stopped.set()
        if self.thread: self.thread.join(timeout=2)

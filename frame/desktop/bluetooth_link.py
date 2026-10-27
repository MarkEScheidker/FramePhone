"""Host BlueZ peripheral. Radio I/O lives on its own asyncio thread."""
import asyncio
import hmac
import hashlib
import json
import os
import threading
import time
import uuid

from bluetooth_protocol import SERVICE, CONTROL, POSE, ControlFragments, bootstrap, decode_pose


class PairingApprovalRequired(ValueError):
    """A valid credential proposal needs explicit consent before replacing trust."""
    def __init__(self, candidate, previous):
        super().__init__('Application pairing confirmation required')
        self.candidate, self.previous = candidate, previous


class BluetoothLink:
    def __init__(self, store, notify):
        self.store, self.notify = store, notify
        self.status = 'Bluetooth starting'
        self.address = None
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread = None
        self.peer = None
        self.expected = None
        self.challenges = {}
        self.fragments = ControlFragments()
        self.pairing = None
        self.bond_approvals = {}
        self.setup_errors = {}
        self.control_reads = {}

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='bluetooth', daemon=True)
            self.thread.start()

    async def confirm_pairing(self, device, passkey=None, kind='bond'):
        with self.lock:
            if self.pairing is not None or self.stopped.is_set():
                return False
            request = dict(device=device, kind=kind, passkey=f'{passkey:06d}' if passkey is not None else '',
                           accepted=False, event=threading.Event())
            self.pairing = request
            if kind == 'bond':
                self.bond_approvals.pop(device, None)
        self.status = 'Confirm the Bluetooth number on both devices' if kind == 'bond' else 'Confirm phone pairing on Steam Frame'
        self.notify('bluetooth_pairing', request)
        try:
            deadline = time.monotonic()+90
            while not request['event'].is_set() and not self.stopped.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(.05)
            accepted = request['event'].is_set() and request['accepted'] and not self.stopped.is_set()
            if accepted and kind == 'bond':
                with self.lock:
                    self.bond_approvals[device] = time.monotonic()+120
            self.status = ('Bluetooth pairing approved — completing encryption' if accepted else
                           'Bluetooth pairing cancelled — retry connection from your phone')
            return accepted
        finally:
            with self.lock:
                if self.pairing is request:
                    self.pairing = None
            self.notify('bluetooth_pairing_closed', request)

    def cancel_pairing(self):
        with self.lock:
            if self.pairing:
                self.pairing['accepted'] = False
                self.pairing['event'].set()

    def authorize(self, session, receive):
        with self.lock:
            self.expected = (session, receive)

    def revoke(self, session):
        with self.lock:
            if self.expected and self.expected[0] == session:
                self.expected = None
                self.peer = None

    def forget(self):
        self.cancel_pairing()
        with self.lock:
            self.expected = self.peer = None
            self.challenges.clear()
            self.fragments = ControlFragments()
            self.bond_approvals.clear()
            self.setup_errors.clear()
            self.control_reads.clear()
            self.store.forget()
        self.status = 'Bluetooth ready — pair from Android'

    def read_control(self, device, offset=0):
        with self.lock:
            now = time.monotonic()
            self.control_reads = {k:v for k,v in self.control_reads.items() if now-v[1] < 15}
            if offset:
                snapshot = self.control_reads.get(device)
                if not snapshot or not 0 <= offset <= len(snapshot[0]):
                    raise ValueError('Invalid Bluetooth read offset')
                return snapshot[0][offset:]
            if device not in self.control_reads and len(self.control_reads) >= 4:
                raise ValueError('Too many Bluetooth setup readers')
            error = self.setup_errors.pop(device, None)
            if error:
                encoded = json.dumps(dict(op='error', code=error, address=self.address), separators=(',', ':')).encode()
                self.control_reads[device] = (encoded, now)
                return encoded
            self.challenges = {k:v for k,v in self.challenges.items() if now-v[1] < 15}
            if device not in self.challenges:
                if len(self.challenges) >= 4:
                    raise ValueError('Too many Bluetooth setup clients')
                self.challenges[device] = (os.urandom(32).hex(), now)
            try:
                paired = self.store.load() is not None
            except (OSError, ValueError):
                self.status = 'Saved pairing is unreadable — use Forget phone, then retry pairing'
                encoded = json.dumps(dict(op='error', code='saved_pairing_invalid', address=self.address), separators=(',', ':')).encode()
                self.control_reads[device] = (encoded, now)
                return encoded
            data = dict(op='challenge', version=1, challenge=self.challenges[device][0], address=self.address, paired=paired)
            if self.peer and self.peer['device'] == device:
                data.update(op='ready', binding=self.peer['binding'], token=self.peer['token'])
            encoded = json.dumps(data, separators=(',', ':')).encode()
            self.control_reads[device] = (encoded, now)
            return encoded

    def control(self, device, value):
        with self.lock:
            message = self.fragments.receive(device, value)
            if message is None:
                return
            if message.get('op') == 'bootstrap':
                challenge = self.challenges.pop(device, None)
                if not challenge or time.monotonic()-challenge[1] > 15 or not self.address:
                    raise ValueError('Bluetooth setup challenge expired')
                saved = self.store.load()
                try:
                    candidate = bootstrap(message, challenge[0], self.address, saved, enroll=not saved)
                except ValueError:
                    if not saved:
                        raise
                    if 'credential' not in message:
                        self.setup_errors[device] = 'pairing_mismatch'
                        return
                    # A reinstall may have a new certificate and verifier. Only
                    # a valid new-credential proof may offer replacement, never
                    # an invalid/replayed message or an unverified route.
                    candidate = bootstrap(message, challenge[0], self.address, None, enroll=True)
                    raise PairingApprovalRequired(candidate, saved)
                if not saved and time.monotonic() >= self.bond_approvals.get(device, 0):
                    raise PairingApprovalRequired(candidate, None)
                self.commit_bootstrap(device, candidate, saved)
            elif message.get('op') == 'bind':
                peer = self.peer
                if not peer or peer['device'] != device or message.get('binding') != peer['binding']:
                    raise ValueError('Bluetooth peer not authenticated')
                session = str(uuid.UUID(message['session']))
                expected = hmac.new(bytes.fromhex(peer['token']), session.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected, str(message.get('proof', ''))):
                    raise ValueError('Invalid Bluetooth session binding')
                peer['session'] = session
                self.status = 'Bluetooth pose channel ready'
            else:
                raise ValueError('Unsupported Bluetooth command')

    def commit_bootstrap(self, device, candidate, previous, replace=False):
        with self.lock:
            current = self.store.load()
            identity = lambda record: (record['pin'], record['credential']) if record else None
            if identity(current) != identity(previous) or self.stopped.is_set():
                raise ValueError('Pairing changed while confirmation was open; try again')
            candidate = dict(candidate, bluetooth=True)
            self.store.save(candidate)
            self.bond_approvals.pop(device, None)
            if replace:
                self.expected = None
                self.notify('bluetooth_replaced', None)
            self.peer = dict(device=device, binding=str(uuid.uuid4()), token=os.urandom(32).hex(), session=None)
            self.status = 'Bluetooth authenticated — connecting Wi-Fi'
            self.notify('bluetooth_endpoint', candidate['host'])

    def pose(self, device, value):
        message, gyro = decode_pose(value)
        with self.lock:
            peer, expected = self.peer, self.expected
            if (not peer or not expected or peer['device'] != device or
                    peer['session'] != message['session'] or expected[0] != message['session']):
                raise ValueError('Unbound Bluetooth pose session')
            # Callback is bounded validation/mailbox work; it never touches Tk.
            expected[1](message, gyro, time.monotonic_ns())

    def _run(self):
        try:
            asyncio.run(self._supervise())
        except ImportError:
            self.status = 'Bluetooth unavailable: install python3-dbus-next for native development'
        except Exception as error:
            self.status = 'Bluetooth stopped: '+str(error)[:160]

    async def _supervise(self):
        while not self.stopped.is_set():
            try:
                await self._serve()
            except Exception as error:
                self.status = 'Bluetooth unavailable: '+str(error)[:160]
            with self.lock:
                self.address = None
                self.peer = None
                self.challenges.clear()
                self.bond_approvals.clear()
                self.setup_errors.clear()
                self.control_reads.clear()
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
        released = asyncio.Event()

        class Service(ServiceInterface):
            def __init__(self):
                super().__init__('org.bluez.GattService1')
            @dbus_property(access=PropertyAccess.READ)
            def UUID(self) -> 's': return SERVICE
            @dbus_property(access=PropertyAccess.READ)
            def Primary(self) -> 'b': return True
            @dbus_property(access=PropertyAccess.READ)
            def Includes(self) -> 'ao': return []

        class Characteristic(ServiceInterface):
            def __init__(self, control):
                super().__init__('org.bluez.GattCharacteristic1')
                self.control = control
            @dbus_property(access=PropertyAccess.READ)
            def UUID(self) -> 's': return CONTROL if self.control else POSE
            @dbus_property(access=PropertyAccess.READ)
            def Service(self) -> 'o': return service_path
            @dbus_property(access=PropertyAccess.READ)
            def Flags(self) -> 'as':
                return (['read', 'write', 'encrypt-authenticated-read', 'encrypt-authenticated-write'] if self.control
                        else ['write-without-response', 'encrypt-authenticated-write'])
            @method()
            def ReadValue(self, options: 'a{sv}') -> 'ay':
                if not self.control: raise DBusError('org.bluez.Error.NotPermitted', 'Write-only pose')
                try:
                    return owner.read_control(options['device'].value, options.get('offset', Variant('q', 0)).value)
                except (ValueError, KeyError) as error:
                    raise DBusError('org.bluez.Error.NotAuthorized', str(error))
            @method()
            async def WriteValue(self, value: 'ay', options: 'a{sv}'):
                try:
                    if options.get('offset', Variant('q', 0)).value:
                        raise ValueError('Use bounded control fragments')
                    device = options['device'].value
                    try:
                        (owner.control if self.control else owner.pose)(device, bytes(value))
                    except PairingApprovalRequired as proposal:
                        kind = 'replace' if proposal.previous else 'enroll'
                        if await owner.confirm_pairing(device, kind=kind):
                            owner.commit_bootstrap(device, proposal.candidate, proposal.previous, replace=True)
                        else:
                            with owner.lock:
                                if len(owner.setup_errors) >= 4:
                                    owner.setup_errors.pop(next(iter(owner.setup_errors)))
                                owner.setup_errors[device] = 'pairing_rejected'
                except OSError:
                    with owner.lock:
                        owner.setup_errors[options['device'].value] = 'pairing_storage_failed'
                    owner.status = 'Cannot save pairing — check desktop configuration permissions'
                except (ValueError, KeyError, TypeError) as error:
                    # Never include inbound payloads, credentials or keys in errors.
                    raise DBusError('org.bluez.Error.NotAuthorized', 'Invalid or unauthorized FramePhone message')

        class Agent(ServiceInterface):
            def __init__(self):
                super().__init__('org.bluez.Agent1')
            @method()
            async def RequestConfirmation(self, device: 'o', passkey: 'u'):
                if not await owner.confirm_pairing(device, passkey):
                    raise DBusError('org.bluez.Error.Rejected', 'Bluetooth number comparison rejected')
            @method()
            def RequestAuthorization(self, device: 'o'):
                raise DBusError('org.bluez.Error.Rejected', 'Number comparison is required; Just Works is not supported')
            @method()
            def RequestPinCode(self, device: 'o') -> 's':
                raise DBusError('org.bluez.Error.Rejected', 'Legacy PIN pairing is not supported')
            @method()
            def RequestPasskey(self, device: 'o') -> 'u':
                raise DBusError('org.bluez.Error.Rejected', 'Number comparison is required')
            @method()
            def DisplayPasskey(self, device: 'o', passkey: 'u', entered: 'q'):
                raise DBusError('org.bluez.Error.Rejected', 'Number comparison is required')
            @method()
            def DisplayPinCode(self, device: 'o', pincode: 's'):
                raise DBusError('org.bluez.Error.Rejected', 'Legacy PIN pairing is not supported')
            @method()
            def AuthorizeService(self, device: 'o', uuid: 's'):
                if uuid.lower() != SERVICE:
                    raise DBusError('org.bluez.Error.Rejected', 'This agent only authorizes FramePhone')
            @method()
            def Cancel(self): owner.cancel_pairing()
            @method()
            def Release(self):
                owner.cancel_pairing()
                released.set()

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

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        manager = advertiser = agent_manager = None
        agent_registered = False
        try:
            reply = await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus', member='GetNameOwner', signature='s', body=['org.bluez']))
            if reply.message_type == MessageType.ERROR:
                raise ValueError('BlueZ is not running')
            bluez_owner = reply.body[0]
            def authorize_sender(message):
                if (message.message_type == MessageType.SIGNAL and message.sender == bluez_owner and
                        message.interface == 'org.freedesktop.DBus.Properties' and message.member == 'PropertiesChanged' and
                        message.body and message.body[0] == 'org.bluez.Device1'):
                    values = message.body[1]
                    lost = any(key in values and not values[key].value for key in ('Connected', 'Paired'))
                    if lost:
                        with owner.lock:
                            if (owner.pairing and owner.pairing['device'] == message.path and
                                    owner.pairing['kind'] != 'bond'):
                                # A transport/profile handoff is not cancellation
                                # of SSP. Only Agent.Cancel/Release, timeout or
                                # the user's rejection ends numeric confirmation.
                                owner.cancel_pairing()
                            if owner.peer and owner.peer['device'] == message.path:
                                owner.peer = None
                                owner.status = ('Bluetooth pairing removed — pair again from your phone' if
                                                'Paired' in values and not values['Paired'].value else
                                                'Bluetooth disconnected — waiting for phone')
                            owner.challenges.pop(message.path, None)
                            owner.fragments.pending.pop(message.path, None)
                            owner.control_reads.pop(message.path, None)
                if (message.message_type == MessageType.METHOD_CALL and message.path and message.path.startswith(base+'/') and
                        (message.interface == 'org.bluez.Agent1' or
                         (message.interface == 'org.bluez.GattCharacteristic1' and message.member in ('ReadValue', 'WriteValue'))) and
                        message.sender != bluez_owner):
                    bus.send(Message.new_error(message, 'org.bluez.Error.NotAuthorized', 'BlueZ owns the radio boundary'))
                    return True
            bus.add_message_handler(authorize_sender)
            tree = await bus.introspect('org.bluez', '/')
            objects = await bus.get_proxy_object('org.bluez', '/', tree).get_interface('org.freedesktop.DBus.ObjectManager').call_get_managed_objects()
            adapter = next((path for path, interfaces in objects.items()
                            if 'org.bluez.GattManager1' in interfaces and 'org.bluez.LEAdvertisingManager1' in interfaces
                            and interfaces.get('org.bluez.Adapter1', {}).get('Powered', Variant('b', False)).value), None)
            if not adapter:
                raise ValueError('enable headset Bluetooth; adapter must support LE advertising and GATT server')
            with self.lock:
                self.address = objects[adapter]['org.bluez.Adapter1']['Address'].value.upper()
            obj = bus.get_proxy_object('org.bluez', adapter, await bus.introspect('org.bluez', adapter))
            obj.get_interface('org.freedesktop.DBus.Properties').on_properties_changed(
                lambda interface, values, invalidated: released.set() if interface == 'org.bluez.Adapter1'
                and 'Powered' in values and not values['Powered'].value else None)
            daemon = bus.get_proxy_object('org.freedesktop.DBus', '/org/freedesktop/DBus',
                await bus.introspect('org.freedesktop.DBus', '/org/freedesktop/DBus'))
            await daemon.get_interface('org.freedesktop.DBus').call_add_match(
                "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',path_namespace='"+adapter+"'")
            daemon.get_interface('org.freedesktop.DBus').on_name_owner_changed(
                lambda name, old, new: released.set() if name == 'org.bluez' and new != bluez_owner else None)
            manager = obj.get_interface('org.bluez.GattManager1')
            advertiser = obj.get_interface('org.bluez.LEAdvertisingManager1')
            # A concrete root makes dbus-next advertise its built-in ObjectManager.
            bus.export(base, ServiceInterface('com.framephone.BluetoothApplication1'))
            bus.export(service_path, Service())
            bus.export(service_path+'/control', Characteristic(True))
            bus.export(service_path+'/pose', Characteristic(False))
            bus.export(base+'/advertisement', Advertisement())
            bus.export(base+'/agent', Agent())
            agents = bus.get_proxy_object('org.bluez', '/org/bluez', await bus.introspect('org.bluez', '/org/bluez'))
            agent_manager = agents.get_interface('org.bluez.AgentManager1')
            # Incoming phone-initiated bonding needs a default agent with actual
            # display/confirmation capability, not the host's possible NoIO agent.
            await agent_manager.call_register_agent(base+'/agent', 'DisplayYesNo')
            agent_registered = True
            await agent_manager.call_request_default_agent(base+'/agent')
            await manager.call_register_application(base, {})
            await advertiser.call_register_advertisement(base+'/advertisement', {})
            self.status = 'Bluetooth ready — pair from Android'
            while not self.stopped.is_set() and bus.connected and not released.is_set():
                await asyncio.sleep(.2)
        finally:
            owner.cancel_pairing()
            for _ in range(10):
                if owner.pairing is None:
                    break
                await asyncio.sleep(.01)
            if advertiser:
                try: await advertiser.call_unregister_advertisement(base+'/advertisement')
                except Exception: pass
            if manager:
                try: await manager.call_unregister_application(base)
                except Exception: pass
            if agent_manager and agent_registered:
                try: await agent_manager.call_unregister_agent(base+'/agent')
                except Exception: pass
            bus.disconnect()

    def close(self):
        self.stopped.set()
        self.cancel_pairing()
        if self.thread:
            self.thread.join(timeout=2)

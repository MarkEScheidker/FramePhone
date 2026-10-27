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

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='bluetooth', daemon=True)
            self.thread.start()

    def authorize(self, session, receive):
        with self.lock:
            self.expected = (session, receive)

    def revoke(self, session):
        with self.lock:
            if self.expected and self.expected[0] == session:
                self.expected = None
                self.peer = None

    def forget(self):
        with self.lock:
            self.expected = self.peer = None
            self.challenges.clear()
            self.fragments = ControlFragments()
            self.store.forget()
        self.status = 'Bluetooth ready — pair from Android'

    def read_control(self, device, offset=0):
        with self.lock:
            now = time.monotonic()
            self.challenges = {k:v for k,v in self.challenges.items() if now-v[1] < 15}
            if device not in self.challenges:
                if len(self.challenges) >= 4:
                    raise ValueError('Too many Bluetooth setup clients')
                self.challenges[device] = (os.urandom(32).hex(), now)
            data = dict(op='challenge', version=1, challenge=self.challenges[device][0], address=self.address)
            if self.peer and self.peer['device'] == device:
                data.update(op='ready', binding=self.peer['binding'], token=self.peer['token'])
            return json.dumps(data, separators=(',', ':')).encode()[offset:]

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
                saved = bootstrap(message, challenge[0], self.address, saved, enroll=not saved)
                saved['bluetooth'] = True
                self.store.save(saved)
                self.peer = dict(device=device, binding=str(uuid.uuid4()), token=os.urandom(32).hex(), session=None)
                self.status = 'Bluetooth authenticated — connecting Wi-Fi'
                self.notify('bluetooth_endpoint', saved['host'])
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
            def WriteValue(self, value: 'ay', options: 'a{sv}'):
                try:
                    if options.get('offset', Variant('q', 0)).value:
                        raise ValueError('Use bounded control fragments')
                    device = options['device'].value
                    (owner.control if self.control else owner.pose)(device, bytes(value))
                except (ValueError, KeyError, TypeError, OSError) as error:
                    # Never include inbound payloads, credentials or keys in errors.
                    raise DBusError('org.bluez.Error.NotAuthorized', 'Invalid or unauthorized FramePhone message')

        class Advertisement(ServiceInterface):
            def __init__(self): super().__init__('org.bluez.LEAdvertisement1')
            @dbus_property(access=PropertyAccess.READ)
            def Type(self) -> 's': return 'peripheral'
            @dbus_property(access=PropertyAccess.READ)
            def ServiceUUIDs(self) -> 'as': return [SERVICE]
            @dbus_property(access=PropertyAccess.READ)
            def LocalName(self) -> 's': return 'FramePhone'
            @method()
            def Release(self): released.set()

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        manager = advertiser = None
        try:
            reply = await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus', member='GetNameOwner', signature='s', body=['org.bluez']))
            if reply.message_type == MessageType.ERROR:
                raise ValueError('BlueZ is not running')
            bluez_owner = reply.body[0]
            def authorize_sender(message):
                if (message.message_type == MessageType.METHOD_CALL and message.path and message.path.startswith(base+'/') and
                        message.interface == 'org.bluez.GattCharacteristic1' and message.member in ('ReadValue', 'WriteValue') and
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
            await manager.call_register_application(base, {})
            await advertiser.call_register_advertisement(base+'/advertisement', {})
            self.status = 'Bluetooth ready — pair from Android'
            while not self.stopped.is_set() and bus.connected and not released.is_set():
                await asyncio.sleep(.2)
        finally:
            if advertiser:
                try: await advertiser.call_unregister_advertisement(base+'/advertisement')
                except Exception: pass
            if manager:
                try: await manager.call_unregister_application(base)
                except Exception: pass
            bus.disconnect()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=2)

"""Exercise the BlueZ service on a private D-Bus without accessing a host radio."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import TestCase

from dbus_next import DBusError, Message, MessageType, PropertyAccess, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property, method

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from bluetooth_link import BluetoothLink
from phone_link import PairingStore

ADAPTER = '/org/bluez/hci0'
DEVICE = ADAPTER + '/dev_phone'
BASE = '/com/framephone/bluetooth'


async def check(address):
    os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = address
    radio = await MessageBus(bus_address=address).connect()
    await radio.request_name('org.bluez')
    radio.export('/', ServiceInterface('com.framephone.Mock'))
    state = dict(owner=None, capability=None, disconnected=0, unregistered=set(),
                 pairable=False, timeout=60, powered=True, registrations=0,
                 fail_registration=False)

    def capture(message):
        if message.member == 'RegisterApplication':
            state['owner'] = message.sender
    radio.add_message_handler(capture)

    class Adapter(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.Adapter1')

        @dbus_property(access=PropertyAccess.READ)
        def Powered(self) -> 'b':
            return state['powered']

        @dbus_property()
        def Pairable(self) -> 'b':
            return state['pairable']

        @Pairable.setter
        def Pairable(self, value: 'b'):
            state['pairable'] = value

        @dbus_property()
        def PairableTimeout(self) -> 'u':
            return state['timeout']

        @PairableTimeout.setter
        def PairableTimeout(self, value: 'u'):
            state['timeout'] = value

    class Device(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.Device1')

        @dbus_property(access=PropertyAccess.READ)
        def Address(self) -> 's':
            return '11:22:33:44:55:66'

        @dbus_property(access=PropertyAccess.READ)
        def Paired(self) -> 'b':
            return True

        @method()
        def Disconnect(self):
            state['disconnected'] += 1

    class Gatt(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.GattManager1')

        @method()
        def RegisterApplication(self, path: 'o', options: 'a{sv}'):
            if state['fail_registration']:
                raise DBusError('org.bluez.Error.Failed', 'Registration rejected for test')
            state['registrations'] += 1

        @method()
        def UnregisterApplication(self, path: 'o'):
            state['unregistered'].add('gatt')

    class Advertiser(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.LEAdvertisingManager1')

        @method()
        def RegisterAdvertisement(self, path: 'o', options: 'a{sv}'):
            pass

        @method()
        def UnregisterAdvertisement(self, path: 'o'):
            state['unregistered'].add('advertisement')

    class Agents(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.AgentManager1')

        @method()
        def RegisterAgent(self, path: 'o', capability: 's'):
            state['capability'] = capability

        @method()
        def RequestDefaultAgent(self, path: 'o'):
            pass

        @method()
        def UnregisterAgent(self, path: 'o'):
            state['unregistered'].add('agent')

    adapter = Adapter()
    for service in (adapter, Gatt(), Advertiser()):
        radio.export(ADAPTER, service)
    radio.export('/org/bluez', Agents())
    radio.export(DEVICE, Device())

    async def interface(owner, path, name):
        tree = await radio.introspect(owner, path)
        return radio.get_proxy_object(owner, path, tree).get_interface(name)

    with tempfile.TemporaryDirectory() as folder:
        events = []
        link = BluetoothLink(PairingStore(Path(folder) / 'pair.json'),
                             lambda *event: events.append(event))
        task = asyncio.create_task(link._supervise())

        async def until(predicate):
            deadline = time.monotonic() + 8
            while not predicate():
                if task.done():
                    await task
                    raise AssertionError('Bluetooth supervisor exited')
                assert time.monotonic() < deadline, link.status
                await asyncio.sleep(.02)

        try:
            await until(link.ready.is_set)
            assert state['pairable'] and state['timeout'] == 0
            assert state['capability'] == 'NoInputNoOutput'
            owner = state['owner']
            agent = await interface(owner, BASE + '/agent', 'org.bluez.Agent1')
            await agent.call_request_authorization(DEVICE)
            assert not events, 'OS bonding attempted app hash verification before TLS'
            path = BASE + '/service0/control'
            properties = await interface(owner, path, 'org.freedesktop.DBus.Properties')
            flags = (await properties.call_get('org.bluez.GattCharacteristic1', 'Flags')).value
            assert 'encrypt-read' in flags and 'encrypt-authenticated-read' not in flags
            control = await interface(owner, path, 'org.bluez.GattCharacteristic1')
            value = await control.call_read_value({'device': Variant('o', DEVICE)})
            assert value and value[0] == 22, 'initial read is not a TLS handshake record'
            rogue = await MessageBus(bus_address=address).connect()
            try:
                reply = await rogue.call(Message(
                    destination=owner, path=path, interface='org.bluez.GattCharacteristic1',
                    member='ReadValue', signature='a{sv}', body=[{'device': Variant('o', DEVICE)}]))
                assert reply.message_type == MessageType.ERROR
                assert reply.error_name == 'org.bluez.Error.NotAuthorized'
            finally:
                rogue.disconnect()
                await rogue.wait_for_disconnect()
            link.forget()
            await until(lambda: state['disconnected'] == 1)

            # Advertisement release rebuilds the server and restores adapter settings.
            advert = await interface(owner, BASE + '/advertisement', 'org.bluez.LEAdvertisement1')
            await advert.call_release()
            await until(lambda: not link.ready.is_set())
            await until(lambda: not state['pairable'] and state['timeout'] == 60)
            assert not link.stopped.is_set(), 'BlueZ release permanently stopped the server'
            await until(lambda: state['registrations'] >= 2 and link.ready.is_set())

            # Failed registration remains visible through Forget and retries automatically.
            state['fail_registration'] = True
            agent = await interface(state['owner'], BASE + '/agent', 'org.bluez.Agent1')
            with TestCase().assertLogs(level='ERROR') as errors:
                await agent.call_release()
                await until(lambda: link.status.startswith('Bluetooth unavailable:'))
            assert 'Registration rejected for test' in '\n'.join(errors.output)
            unavailable = link.status
            link.forget()
            assert link.status == unavailable and not link.ready.is_set()
            state['fail_registration'] = False
            await until(lambda: state['registrations'] >= 3 and link.ready.is_set())

            # Losing BlueZ ownership also retires and rebuilds the service.
            await radio.release_name('org.bluez')
            await until(lambda: not link.ready.is_set())
            await radio.request_name('org.bluez')
            await until(lambda: state['registrations'] >= 4 and link.ready.is_set())

            # A power cycle cannot leave the old registration marked ready.
            state['powered'] = False
            adapter.emit_properties_changed({'Powered': False})
            await until(lambda: not link.ready.is_set())
            state['powered'] = True
            adapter.emit_properties_changed({'Powered': True})
            await until(lambda: state['registrations'] >= 5 and link.ready.is_set())
        finally:
            link.stopped.set()
            await asyncio.wait_for(task, 3)
            radio.disconnect()
            await radio.wait_for_disconnect()
        assert state['unregistered'] == {'gatt', 'advertisement', 'agent'}
        assert not state['pairable'] and state['timeout'] == 60
    print('Private D-Bus: bonding readiness, admission, encrypted GATT, service recovery, '
          'visible errors and adapter restoration passed')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as folder:
        process = subprocess.Popen(
            ['dbus-daemon', '--session', '--nofork', '--print-address=1',
             '--address=unix:path=' + folder + '/bus'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            asyncio.run(check(process.stdout.readline().strip()))
        finally:
            process.terminate()
            process.wait(timeout=3)

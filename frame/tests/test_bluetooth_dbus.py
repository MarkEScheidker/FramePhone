"""Actual GATT API on a private bus with simulated BlueZ; no radio/root required."""
import asyncio,json,os,struct,sys,tempfile,subprocess
from pathlib import Path
r=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(r/'frame/desktop'));sys.path.insert(0,str(r/'frame/tests'))
from dbus_next import Variant,BusType,DBusError,PropertyAccess,Message,MessageType
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface,method,dbus_property
from bluetooth_link import BluetoothLink
from phone_link import PairingStore
from test_bluetooth import fragments,hello,GOLDEN
import hashlib,hmac,uuid

async def check(address):
    os.environ['DBUS_SYSTEM_BUS_ADDRESS']=address
    radio=await MessageBus(bus_address=address).connect()
    await radio.request_name('org.bluez')
    radio.export('/',ServiceInterface('org.framephone.MockRoot'))
    remote={'name':None,'unregistered':set()}
    def capture(message):
        if message.member=='RegisterApplication' and message.message_type==MessageType.METHOD_CALL:remote['name']=message.sender
    radio.add_message_handler(capture)
    class Adapter(ServiceInterface):
        def __init__(self):super().__init__('org.bluez.Adapter1')
        @dbus_property(access=PropertyAccess.READ)
        def Address(self)->'s':return 'AA:BB:CC:DD:EE:FF'
        @dbus_property(access=PropertyAccess.READ)
        def Powered(self)->'b':return True
    class Manager(ServiceInterface):
        def __init__(self):super().__init__('org.bluez.GattManager1')
        @method()
        def RegisterApplication(self,path:'o',options:'a{sv}'):pass
        @method()
        def UnregisterApplication(self,path:'o'):remote['unregistered'].add('gatt')
    class Advertising(ServiceInterface):
        def __init__(self):super().__init__('org.bluez.LEAdvertisingManager1')
        @method()
        def RegisterAdvertisement(self,path:'o',options:'a{sv}'):pass
        @method()
        def UnregisterAdvertisement(self,path:'o'):remote['unregistered'].add('advertisement')
    for interface in (Adapter(),Manager(),Advertising()):radio.export('/org/bluez/hci0',interface)
    with tempfile.TemporaryDirectory() as d:
        link=BluetoothLink(PairingStore(Path(d)/'pairing.json'),lambda *v:None)
        task=asyncio.create_task(link._serve())
        try:
            for _ in range(100):
                if link.status.startswith('Bluetooth ready'):break
                if task.done():await task
                await asyncio.sleep(.02)
            assert link.address=='AA:BB:CC:DD:EE:FF',link.status
            name=remote['name'];assert name
            base='/com/framephone/bluetooth'
            obj=radio.get_proxy_object(name,base,await radio.introspect(name,base))
            managed=await obj.get_interface('org.freedesktop.DBus.ObjectManager').call_get_managed_objects()
            flags=managed[base+'/service0/control']['org.bluez.GattCharacteristic1']['Flags'].value
            assert 'encrypt-authenticated-write' in flags and 'encrypt-authenticated-read' in flags
            control=radio.get_proxy_object(name,base+'/service0/control',await radio.introspect(name,base+'/service0/control')).get_interface('org.bluez.GattCharacteristic1')
            options={'device':Variant('o','/org/bluez/hci0/dev_phone')}
            challenge=json.loads(await control.call_read_value(options))['challenge']
            for part in fragments(hello(challenge=challenge)):await control.call_write_value(part,options)
            ready=json.loads(await control.call_read_value(options));session=str(uuid.UUID(int=1));received=[]
            link.authorize(session,lambda *v:received.append(v))
            bind=dict(op='bind',session=session,binding=ready['binding'],proof=hmac.new(bytes.fromhex(ready['token']),session.encode(),hashlib.sha256).hexdigest())
            for part in fragments(bind):await control.call_write_value(part,options)
            pose=radio.get_proxy_object(name,base+'/service0/pose',await radio.introspect(name,base+'/service0/pose')).get_interface('org.bluez.GattCharacteristic1')
            await pose.call_write_value(GOLDEN,options)
            assert len(received)==1 and received[0][0]['seq']==17
            rogue=await MessageBus(bus_address=address).connect()
            try:
                bypass=rogue.get_proxy_object(name,base+'/service0/control',await rogue.introspect(name,base+'/service0/control')).get_interface('org.bluez.GattCharacteristic1')
                try:await bypass.call_read_value(options)
                except DBusError as error:assert error.type=='org.bluez.Error.NotAuthorized'
                else:raise AssertionError('local caller bypassed the BlueZ radio boundary')
            finally:
                rogue.disconnect(); await rogue.wait_for_disconnect()
        finally:
            link.stopped.set()
            await asyncio.wait_for(task,3)
            radio.disconnect(); await radio.wait_for_disconnect()
        assert remote['unregistered']=={'gatt','advertisement'},remote
    print('Private D-Bus GATT/advertisement registration, authenticated bootstrap, pose delivery, sender authorization and cleanup passed')

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='framephone-ble-bus-') as directory:
        daemon=subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1','--address=unix:path='+directory+'/bus'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            address=daemon.stdout.readline().strip()
            assert address
            asyncio.run(check(address))
        finally:
            daemon.terminate();daemon.wait(timeout=3)

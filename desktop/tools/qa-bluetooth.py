#!/usr/bin/env python3
"""Finite BlueZ protocol QA on a fresh private bus; never accesses real hardware."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ADAPTER_PATH='/org/bluez/hci0';DEVICE_PATH=ADAPTER_PATH+'/dev_00_11_22_33_44_55'


def fixture():
    sys.path.append('/usr/lib/python3/dist-packages')
    from gi.repository import Gio,GLib
    pairing_kind=os.environ.get('ORBIT_BT_CODE_QA','confirm')
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    xml='''<node>
<interface name="org.freedesktop.DBus.ObjectManager"><method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method><signal name="InterfacesRemoved"><arg type="o"/><arg type="as"/></signal></interface>
<interface name="org.bluez.Adapter1"><method name="StartDiscovery"/><method name="StopDiscovery"/><method name="RemoveDevice"><arg type="o" direction="in"/></method><property name="Powered" type="b" access="readwrite"/><property name="Discovering" type="b" access="read"/></interface>
<interface name="org.bluez.Device1"><method name="Pair"/><method name="CancelPairing"/><method name="Connect"/><method name="Disconnect"/><property name="Alias" type="s" access="read"/><property name="Adapter" type="o" access="read"/><property name="Paired" type="b" access="read"/><property name="Connected" type="b" access="read"/><property name="Trusted" type="b" access="read"/></interface>
<interface name="org.bluez.AgentManager1"><method name="RegisterAgent"><arg type="o" direction="in"/><arg type="s" direction="in"/></method><method name="UnregisterAgent"><arg type="o" direction="in"/></method></interface>
<interface name="org.bluez.Battery1"><property name="Percentage" type="y" access="read"/></interface>
</node>'''
    info=Gio.DBusNodeInfo.new_for_xml(xml)
    adapter={'Powered':False,'Discovering':False};device={'Alias':'Private test headphones','Adapter':ADAPTER_PATH,'Paired':False,'Connected':False,'Trusted':False};agent=[];pending=[];present=[True];battery={'Percentage':82}
    def variant(key,value):return GLib.Variant('y' if key=='Percentage' else 'o' if key=='Adapter' else 'b' if isinstance(value,bool) else 's',value)
    def props(values):return {key:variant(key,value) for key,value in values.items()}
    def changed(path,interface,values):bus.emit_signal(None,path,'org.freedesktop.DBus.Properties','PropertiesChanged',GLib.Variant('(sa{sv}as)',(interface,props(values),[])))
    def complete_pair(connection,result,*_):
        if not pending:return
        invocation=pending.pop()
        try:
            answer=connection.call_finish(result).unpack()
            assert answer==(('0000',) if pairing_kind=='pin' else (123,) if pairing_kind=='passkey' else ())
            device['Paired']=True;changed(DEVICE_PATH,'org.bluez.Device1',{'Paired':True});invocation.return_value(GLib.Variant('()',()))
        except Exception:invocation.return_dbus_error('org.bluez.Error.Rejected','Test confirmation rejected')
    def method(connection,sender,path,interface,name,parameters,invocation):
        args=parameters.unpack();print(json.dumps({'method':name,'args':args}),flush=True)
        if name=='GetManagedObjects':
            objects={ADAPTER_PATH:{'org.bluez.Adapter1':props(adapter)}}
            if present[0]:objects[DEVICE_PATH]={'org.bluez.Device1':props(device),'org.bluez.Battery1':props(battery)}
            invocation.return_value(GLib.Variant('(a{oa{sa{sv}}})',(objects,)));return
        if name=='RegisterAgent':agent[:]=[sender,args[0]];assert args[1]=='KeyboardDisplay'
        elif name=='UnregisterAgent':agent.clear()
        elif name in ('StartDiscovery','StopDiscovery'):
            adapter['Discovering']=name=='StartDiscovery';changed(ADAPTER_PATH,'org.bluez.Adapter1',{'Discovering':adapter['Discovering']})
        elif name=='Pair':
            assert agent,'Agent must register before pairing';pending.append(invocation)
            method={'pin':'RequestPinCode','passkey':'RequestPasskey'}.get(pairing_kind,'RequestConfirmation')
            params=GLib.Variant('(o)',(DEVICE_PATH,)) if pairing_kind in ('pin','passkey') else GLib.Variant('(ou)',(DEVICE_PATH,123))
            connection.call(agent[0],agent[1],'org.bluez.Agent1',method,params,None,0,5000,None,complete_pair,None);return
        elif name=='CancelPairing':
            if pending:pending.pop().return_dbus_error('org.bluez.Error.Canceled','Test pairing canceled')
        elif name in ('Connect','Disconnect'):
            device['Connected']=name=='Connect';changed(DEVICE_PATH,'org.bluez.Device1',{'Connected':device['Connected']})
            if name=='Connect':battery['Percentage']=63;changed(DEVICE_PATH,'org.bluez.Battery1',battery)
        elif name=='RemoveDevice':
            assert args[0]==DEVICE_PATH;present[0]=False;bus.emit_signal(None,'/','org.freedesktop.DBus.ObjectManager','InterfacesRemoved',GLib.Variant('(oas)',(DEVICE_PATH,['org.bluez.Device1'])))
        invocation.return_value(GLib.Variant('()',()))
    def get_prop(connection,sender,path,interface,name):return variant(name,(battery if interface=='org.bluez.Battery1' else adapter if path==ADAPTER_PATH else device)[name])
    def set_prop(connection,sender,path,interface,name,value):
        assert path==ADAPTER_PATH and name=='Powered';adapter[name]=value.unpack();print(json.dumps({'method':'SetPowered','value':adapter[name]}),flush=True);changed(path,interface,{name:adapter[name]});return True
    bus.register_object('/',info.interfaces[0],method,None,None)
    bus.register_object(ADAPTER_PATH,info.interfaces[1],method,get_prop,set_prop)
    bus.register_object(DEVICE_PATH,info.interfaces[2],method,get_prop,None)
    bus.register_object('/org/bluez',info.interfaces[3],method,None,None)
    bus.register_object(DEVICE_PATH,info.interfaces[4],method,get_prop,None)
    bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.bluez',4)),None,0,1000,None)
    print('READY',flush=True);GLib.MainLoop().run()


if '--fixture' in sys.argv:
    fixture();sys.exit()
if '--private' not in sys.argv:
    sys.exit(subprocess.call(['dbus-run-session','--',sys.executable,__file__,'--private']))
# Both BlueZ fixture and controller are now confined to this disposable bus.
os.environ['DBUS_SYSTEM_BUS_ADDRESS']=os.environ['DBUS_SESSION_BUS_ADDRESS']
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(ROOT))
from qt_compat import QApplication,QTimer
from bluetooth import BluetoothControls
service=subprocess.Popen(['/usr/bin/python3',__file__,'--fixture'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
assert service.stdout.readline().strip()=='READY','Private BlueZ fixture did not start'
app=QApplication([]);controls=BluetoothControls();stage=0;notices=[];failures=[]
controls.notice.connect(notices.append)

def check():
    global stage
    if stage==0 and controls.state['available']:
        assert not controls.state['powered'] and not controls.state['discovering'];assert controls.devices[0]['batteryPresent'] and controls.devices[0]['batteryPercent']==82;controls.setPowered(True);stage=1
    elif stage==1 and controls.state['powered']:
        controls.startDiscovery();stage=2
    elif stage==2 and controls.state['discovering']:
        controls.stopDiscovery();stage=3
    elif stage==3 and not controls.state['discovering'] and not controls.state['busy']:
        controls.pairDevice(DEVICE_PATH);stage=4
    elif stage==4 and controls.pairing.get('mode') in ('confirm','pin','passkey'):
        mode=controls.pairing['mode']
        if mode=='pin':controls.submitPinCode('0000')
        elif mode=='passkey':controls.submitPasskey('000123')
        else:assert controls.pairing['passkey']=='000123';controls.answerPairing(True)
        stage=5
    elif stage==5 and controls.devices and controls.devices[0]['paired'] and not controls.state['busy']:
        controls.connectDevice(DEVICE_PATH);stage=6
    elif stage==6 and controls.devices[0]['connected'] and controls.devices[0]['batteryPercent']==63 and not controls.state['busy']:
        controls.disconnectDevice(DEVICE_PATH);stage=7
    elif stage==7 and not controls.devices[0]['connected'] and not controls.state['busy']:
        controls.forgetDevice(DEVICE_PATH);stage=8
    elif stage==8 and not controls.devices and not controls.state['busy']:
        timer.stop();app.quit()

def tick():
    try:check()
    except Exception as error:failures.append(str(error));app.exit(1)
timer=QTimer();timer.timeout.connect(tick);timer.start(30)
QTimer.singleShot(12000,lambda:(failures.append('Timed out at stage '+str(stage)),app.exit(1)))
try:
    result=app.exec();controls.close()
    service.terminate();stdout,stderr=service.communicate(timeout=4)
    operations=[json.loads(line) for line in stdout.splitlines() if line.startswith('{')]
    assert not failures,failures
    assert stage==8,stage
    assert not notices,notices
    methods=[item['method'] for item in operations]
    for method in ('RegisterAgent','StartDiscovery','StopDiscovery','Pair','Connect','Disconnect','RemoveDevice','UnregisterAgent'):assert method in methods,methods
    assert methods.count('StartDiscovery')==methods.count('StopDiscovery')==1,methods
    assert [item['value'] for item in operations if item['method']=='SetPowered']==[True],operations
    print(json.dumps({'private_bluez':True,'pairing_kind':os.environ.get('ORBIT_BT_CODE_QA','confirm'),'battery_percentage_updates':True,'operations':methods,'notices':notices,'hardware_access':False}),flush=True)
    sys.exit(result)
finally:
    controls.close()
    if service.poll() is None:service.terminate();service.wait(timeout=4)

#!/usr/bin/env python3
"""Finite production notification protocol test on a fresh private D-Bus only."""
import json,os,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT

def probe():
    if os.environ.get('ORBIT_PRIVATE_NOTIFICATION_QA')!='1':raise RuntimeError('Run through the private-bus launcher')
    sys.path[:0]=[str(SOURCE_ROOT),'/usr/lib/python3/dist-packages']
    from gi.repository import Gio,GLib
    from system_services import BusEvents,NOTIFICATION_XML
    from types import SimpleNamespace
    address=os.environ['DBUS_SESSION_BUS_ADDRESS'];flags=Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT|Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    def connect():return Gio.DBusConnection.new_for_address_sync(address,flags,None,None)
    events=[]
    bus=BusEvents.__new__(BusEvents);bus.owner=SimpleNamespace(incoming=SimpleNamespace(emit=events.append));bus.GLib=GLib;bus.Gio=Gio;bus.counter=0;bus.records={};bus.records_lock=threading.RLock();bus.owns_notifications=True;bus.connection=connect()
    info=Gio.DBusNodeInfo.new_for_xml(NOTIFICATION_XML)
    registered=bus.connection.register_object('/org/freedesktop/Notifications',info.interfaces[0],bus.method,None,None)
    bus.connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.Notifications',4)),None,0,2000,None)
    loop=GLib.MainLoop();result={};errors=[]
    def worker():
        clients=[]
        try:
            first=connect();other=connect();clients=[first,other];received=[];unrelated=[]
            first.signal_subscribe(None,'org.freedesktop.Notifications','ActionInvoked',None,None,0,lambda *args:received.append(args[5].unpack()))
            other.signal_subscribe(None,'org.freedesktop.Notifications','ActionInvoked',None,None,0,lambda *args:unrelated.append(args[5].unpack()))
            def call(client,method,params):return client.call_sync('org.freedesktop.Notifications','/org/freedesktop/Notifications','org.freedesktop.Notifications',method,params,None,0,3000,None).unpack()
            def notify(client,replaces=0,summary='First'):
                return call(client,'Notify',GLib.Variant('(susssasa{sv}i)',('Fixture',replaces,'',summary,'Plain body',['default','Open'],{'desktop-entry':GLib.Variant('s','fixture'),'resident':GLib.Variant('b',True)},5000)))[0]
            capabilities=call(first,'GetCapabilities',GLib.Variant('()',()))[0];assert 'actions' in capabilities
            ident=notify(first);note=events[-1];assert note['sender']==first.get_unique_name() and note['desktopEntry']=='fixture';assert note['actions']==[dict(key='default',label='Open')]
            assert notify(first,ident,'Replacement')==ident;replacement=events[-1];assert replacement['summary']=='Replacement'
            assert bus.invokeAction(note,'default') is False,'A replaced notification action stayed usable'
            stolen=notify(other,ident,'Other');assert stolen!=ident,'An unrelated sender replaced another app notification'
            assert bus.invokeAction(replacement,'default') is True
            until=time.monotonic()+2
            while not received and time.monotonic()<until:time.sleep(.01)
            assert received==[(ident,'default')],received;time.sleep(.05);assert not unrelated,unrelated
            assert bus.invokeAction(replacement,'not-declared') is False
            before=len(events)
            try:call(other,'CloseNotification',GLib.Variant('(u)',(ident,)))
            except GLib.Error:pass
            assert not any(event.get('close')==ident for event in events[before:]),'Wrong sender closed notification'
            call(first,'CloseNotification',GLib.Variant('(u)',(ident,)))
            assert events[-1].get('close')==ident
            result.update(capabilities=capabilities,sender_action_received=True,unrelated_client_received_action=False,same_owner_replacement=True,foreign_replacement_refused=True,foreign_close_refused=True,private_bus=True)
        except BaseException as error:errors.append(repr(error))
        finally:
            for client in clients:client.close_sync(None)
            GLib.idle_add(loop.quit)
    thread=threading.Thread(target=worker,daemon=True);thread.start();GLib.timeout_add_seconds(12,lambda:(errors.append('probe timeout'),loop.quit(),False)[-1]);loop.run();thread.join(timeout=1)
    bus.connection.unregister_object(registered);bus.connection.close_sync(None)
    if errors:raise RuntimeError('; '.join(errors))
    print(json.dumps(result,sort_keys=True))

def main():
    if '--private' in sys.argv:return probe()
    env=os.environ.copy();env['ORBIT_PRIVATE_NOTIFICATION_QA']='1'
    return subprocess.run(['dbus-run-session','--',sys.executable,str(Path(__file__).resolve()),'--private'],env=env,timeout=20,check=True).returncode
if __name__=='__main__':raise SystemExit(main())

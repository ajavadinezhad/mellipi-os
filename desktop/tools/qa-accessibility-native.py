#!/usr/bin/env python3
"""Inspect real Qt Quick accessibility on private native Wayland + AT-SPI bus."""
import json,os,signal,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))

def wait(check,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=check()
        if result:return result
        time.sleep(.05)
    raise AssertionError('Private accessibility fixture timed out')
def stop(process):
    if process and process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:return
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
FIXTURE='''import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src' if (Path(sys.argv[1])/'src').is_dir() else Path(sys.argv[1])))
from qt_compat import QApplication,QObject,Property,Signal,Slot,QQmlApplicationEngine
class Style(QObject):
 settingsChanged=Signal()
 compact=Property(bool,lambda s:True,constant=True)
 economy=Property(bool,lambda s:True,constant=True)
 themeMode=Property(str,lambda s:'dark',constant=True)
 accentColor=Property(str,lambda s:'#a9d9c3',constant=True)
 appearance=Property('QVariantMap',lambda s:dict(shellLayout='fold',corners='soft',reducedMotion=True),constant=True)
 @Slot()
 def hideTooltip(self):pass
 @Slot(QObject,str,float,float)
 def queueItemTooltip(self,*args):pass
app=QApplication([]);app.setApplicationName('Abstract accessibility fixture')
engine=QQmlApplicationEngine();style=Style();engine.rootContext().setContextProperty('Orbit',style)
uri=(Path(sys.argv[1])/'native').as_uri()
engine.loadData(('import QtQuick 2.15\\nimport QtQuick.Controls 2.15\\nimport QtQuick.Window 2.15\\nimport "'+uri+'" as Ui\\nWindow{id:fixtureWindow;property bool applied:false;visible:true;width:480;height:240;title:"Abstract accessibility fixture";Column{anchors.centerIn:parent;spacing:20;TextField{Accessible.name:"Write here";placeholderText:"Write here"}Ui.OrbitButton{text:"Apply example";onClicked:fixtureWindow.applied=true}Text{text:fixtureWindow.applied?"Applied example":"Ready";Accessible.name:text}}}').encode())
assert engine.rootObjects()
from PyQt5.QtDBus import QDBusConnection
from PyQt5.QtCore import QTimer
QTimer.singleShot(2000,lambda:print('Qt AT-SPI connection established:',QDBusConnection('a11y').isConnected(),flush=True))
app.exec()
'''
def main():
    if '--private-bus' not in sys.argv:
        env={k:v for k,v in os.environ.items() if k not in ('DBUS_SESSION_BUS_ADDRESS','AT_SPI_BUS_ADDRESS','WAYLAND_DISPLAY','DISPLAY','SWAYSOCK','ORBIT_NATIVE_CONTROL')}
        return subprocess.call(['dbus-run-session','--','/usr/bin/python3',__file__,'--private-bus',*(['--enable-later'] if '--enable-later' in sys.argv else [])],env=env)
    parent=native=fixture=None
    with tempfile.TemporaryDirectory(prefix='abstract-a11y-') as directory,open('/tmp/abstract-a11y-native.log','w') as log:
        base=Path(directory);runtime=base/'runtime';runtime.mkdir(mode=0o700);config=base/'sway.conf';config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\n')
        env=dict(os.environ,XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(base/'config'),XDG_DATA_HOME=str(base/'data'),XDG_STATE_HOME=str(base/'state'),WLR_BACKENDS='headless',WLR_RENDERER='pixman',WLR_LIBINPUT_NO_DEVICES='1',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','AT_SPI_BUS_ADDRESS'):env.pop(key,None)
        try:
            parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh;exec sway -c "$1"','abstract-a11y',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            socket=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
            native_log=base/'native.log'
            with native_log.open('w') as stream:native=subprocess.Popen([str(ROOT/'.native-runtime/bin/orbit-compositor')],env=dict(env,WAYLAND_DISPLAY=socket.name,WINIT_UNIX_BACKEND='wayland'),cwd=ROOT,stdout=stream,stderr=stream,start_new_session=True)
            def ready():
                assert native.poll() is None,native_log.read_text()
                for line in native_log.read_text().splitlines():
                    try:
                        row=json.loads(line)
                        if row.get('ready'):return row
                    except ValueError:pass
            info=wait(ready)
            # Service activation must use the owned runtime too, not the parent
            # desktop's AT-SPI socket/cache directories.
            for key in ('XDG_RUNTIME_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME'):os.environ[key]=env[key]
            subprocess.run(['dbus-update-activation-environment','XDG_RUNTIME_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME'],env=env,check=True)
            import gi;gi.require_version('Gio','2.0');from gi.repository import Gio,GLib
            bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
            bus.call_sync('org.a11y.Bus','/org/a11y/bus','org.freedesktop.DBus.Properties','Set',GLib.Variant('(ssv)',('org.a11y.Status','ScreenReaderEnabled',GLib.Variant('b','--enable-later' not in sys.argv))),None,Gio.DBusCallFlags.NONE,5000,None)
            bus.call_sync('org.a11y.Bus','/org/a11y/bus','org.freedesktop.DBus.Properties','Set',GLib.Variant('(ssv)',('org.a11y.Status','IsEnabled',GLib.Variant('b','--enable-later' not in sys.argv))),None,Gio.DBusCallFlags.NONE,5000,None)
            address=bus.call_sync('org.a11y.Bus','/org/a11y/bus','org.a11y.Bus','GetAddress',None,None,Gio.DBusCallFlags.NONE,5000,None).unpack()[0]
            os.environ['AT_SPI_BUS_ADDRESS']=address
            env.pop('QT_ACCESSIBILITY',None)
            env.pop('QT_LINUX_ACCESSIBILITY_ALWAYS_ON',None)
            child=dict(env,QT_LOGGING_RULES='qt.accessibility.*=true',QT_NO_XDG_DESKTOP_PORTAL='1',WAYLAND_DISPLAY=info['wayland_display'],QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell',ORBIT_QT='5',AT_SPI_BUS_ADDRESS=address)
            gi.require_version('Atspi','2.0');from gi.repository import Atspi
            Atspi.init()
            listener=Atspi.EventListener.new(lambda *args:None)
            listener.register('object:children-changed')
            Atspi.get_desktop(0)
            fixture_command=['/usr/bin/python3','-c',FIXTURE,str(ROOT)]
            if os.environ.get('ORBIT_A11Y_GDB')=='1':fixture_command=['gdb','--batch','-ex','run','-ex','thread apply all bt','--args',*fixture_command]
            fixture=subprocess.Popen(fixture_command,env=child,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            if '--enable-later' in sys.argv:
                wait(lambda:'Qt AT-SPI connection established:' in Path('/tmp/abstract-a11y-native.log').read_text())
                assert 'Qt AT-SPI connection established: False' in Path('/tmp/abstract-a11y-native.log').read_text()
                for property_name in ('ScreenReaderEnabled','IsEnabled'):
                    bus.call_sync('org.a11y.Bus','/org/a11y/bus','org.freedesktop.DBus.Properties','Set',GLib.Variant('(ssv)',('org.a11y.Status',property_name,GLib.Variant('b',True))),None,Gio.DBusCallFlags.NONE,5000,None)
            gi.require_version('Atspi','2.0');from gi.repository import Atspi
            Atspi.set_timeout(1500,1500)
            def labels():
                assert fixture.poll() is None,Path('/tmp/abstract-a11y-native.log').read_text()
                while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
                stack=[Atspi.get_desktop(0)];found=set();seen=0;nodes={}
                while stack and seen<256:
                    item=stack.pop();seen+=1
                    try:
                        name=item.get_name() or '';found.add(name);nodes.setdefault(name,[]).append(item)
                        stack.extend(item.get_child_at_index(i) for i in range(min(item.get_child_count(),64)))
                    except Exception:continue
                if {'Write here','Apply example'}<=found:return found,nodes
                return None
            try:found=wait(labels)
            except AssertionError as error:
                raise AssertionError('AT-SPI did not expose the real Qt Quick controls. Fixture log: '+Path('/tmp/abstract-a11y-native.log').read_text()[-6000:]) from error
            found,nodes=found
            print('AT-SPI matching controls:',[(name,[(item.get_role_name(),list(item.get_interfaces())) for item in nodes[name]]) for name in ('Write here','Apply example')],flush=True)
            field=next((item for item in nodes['Write here'] if item.get_editable_text_iface() is not None),nodes['Write here'][0])
            button=next(item for item in nodes['Apply example'] if item.get_action_iface() is not None)
            action=button.get_action_iface();assert action.get_n_actions()>0 and action.do_action(0)
            print('PASS real AT-SPI button activation',flush=True)
            assert field.get_component_iface().grab_focus()
            initial=Atspi.Text.get_text(field,0,-1)
            sys.path.insert(0,str(ROOT/'tools'));from qa_wayland_input import VirtualPointer
            pointer=VirtualPointer(dict(env,WAYLAND_DISPLAY=socket.name))
            try:
                stamp=int(time.monotonic()*1000)&0xffffffff
                pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,30,1))
                pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,30,0));pointer.roundtrip()
                wait(lambda:Atspi.Text.get_text(field,0,-1)!=initial)
            finally:pointer.close()
            wait(lambda:bool((current:=labels()) and 'Applied example' in current[0]))
            print('PASS real native Qt Quick exposes editable field and Abstract button to private AT-SPI')
            print('PASS AT-SPI focuses/reads the real text field after private keyboard input and invokes the real button')
            print(json.dumps(dict(private_bus=True,labels=sorted(found),physical_session_untouched=True,enabled_after_launch='--enable-later' in sys.argv)))
        finally:
            stop(fixture);stop(native);stop(parent)
if __name__=='__main__':sys.exit(main())

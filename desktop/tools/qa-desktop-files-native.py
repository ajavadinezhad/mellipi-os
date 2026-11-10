#!/usr/bin/env python3
"""Real URI drag across separate clients in a private native desktop.

Every compositor/input socket/file/app belongs to the temporary fixture. No host
session is queried. This exercises the actual DesktopIcons QML and controller.
"""
import json,os,signal,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT));sys.path.insert(0,str(ROOT/'tools'))
from native_compositor import NativeCompositor
from qa_wayland_input import VirtualPointer

def wait(check,seconds=12):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        result=check()
        if result:return result
        time.sleep(.03)
    raise AssertionError('Private desktop file QA timed out')
def stop(process):
    if process and process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
SOURCE='''import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src' if (Path(sys.argv[1])/'src').is_dir() else Path(sys.argv[1])))
from qt_compat import QApplication,QObject,Signal,Property,Slot,QQmlApplicationEngine
from desktop_icons import DesktopIcons
from native_app import Icons
class Style(QObject):
 settingsChanged=Signal()
 compact=Property(bool,lambda s:True,constant=True)
 economy=Property(bool,lambda s:True,constant=True)
 themeMode=Property(str,lambda s:'dark',constant=True)
 accentColor=Property(str,lambda s:'#a9d9c3',constant=True)
 appearance=Property('QVariantMap',lambda s:dict(corners='soft',darkLevel='black',reducedMotion=True),constant=True)
 @Slot()
 def hideTooltip(self):pass
 @Slot(QObject,str,float,float)
 def queueItemTooltip(self,*_):pass
app=QApplication([]);app.setApplicationName('abstract-file-source');app.setDesktopFileName('abstract-file-source')
style=Style();files=DesktopIcons(enabled=True,directory=sys.argv[2],places=False)
engine=QQmlApplicationEngine();engine.addImageProvider('icons',Icons());engine.rootContext().setContextProperty('Orbit',style);engine.rootContext().setContextProperty('DesktopFiles',files)
qml='import QtQuick 2.15\\nimport QtQuick.Window 2.15\\nimport "'+(Path(sys.argv[1])/'native').as_uri()+'" as Ui\\nWindow {visible:true;width:400;height:500;flags:Qt.FramelessWindowHint;title:"Mellipi owned file source";Ui.DesktopIcons{anchors.fill:parent;controller:DesktopFiles;outputId:"fixture"}}'
engine.loadData(qml.encode());assert engine.rootObjects();app.aboutToQuit.connect(files.close);app.exec()
'''
RECEIVER='''import sys,json
from pathlib import Path
from PyQt5.QtWidgets import QApplication,QLabel
from PyQt5.QtCore import Qt
class Receiver(QLabel):
 def dragEnterEvent(self,event):
  if event.mimeData().hasUrls():event.acceptProposedAction()
 def dropEvent(self,event):
  Path(sys.argv[1]).write_text(json.dumps([url.toLocalFile() for url in event.mimeData().urls()]));event.acceptProposedAction()
a=QApplication([]);a.setApplicationName('abstract-file-receiver');a.setDesktopFileName('abstract-file-receiver');w=Receiver('Drop a file');w.setWindowFlags(Qt.FramelessWindowHint);w.setWindowTitle('Mellipi owned file receiver');w.resize(380,500);w.setAcceptDrops(True);w.show();a.exec()
'''
def main():
    parent=native=source=receiver=None;pointer=None
    with tempfile.TemporaryDirectory(prefix='abstract-file-native-') as temp,open('/tmp/abstract-file-native-qa.log','w') as log:
        base=Path(temp);runtime=base/'runtime';runtime.mkdir(mode=0o700);files=base/'Desktop';files.mkdir();fixture=files/'fixture.txt';fixture.write_text('owned file drag fixture');received=base/'received.json'
        conf=base/'sway.conf';conf.write_text('output HEADLESS-1 mode 1120x760\nseat seat0 fallback true\nfocus_follows_mouse no\n')
        env={key:value for key,value in os.environ.items() if key not in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','DBUS_SESSION_BUS_ADDRESS')}
        env.update(XDG_RUNTIME_DIR=str(runtime),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        try:
            parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh;exec sway -c "$1"','abstract-file-qa',str(conf)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            parent_socket=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None));sway_socket=wait(lambda:next(runtime.glob('sway-ipc*.sock'),None))
            outer=dict(env,WAYLAND_DISPLAY=parent_socket.name,SWAYSOCK=str(sway_socket));os.environ['SWAYSOCK']=str(sway_socket)
            native_env=dict(env,WAYLAND_DISPLAY=parent_socket.name,WINIT_UNIX_BACKEND='wayland',ORBIT_NATIVE_REDUCED_MOTION='1')
            native_log=base/'native.log'
            with native_log.open('w') as stream:native=subprocess.Popen([str(ROOT/'.native-runtime/bin/orbit-compositor')],cwd=ROOT,env=native_env,stdout=stream,stderr=stream,start_new_session=True)
            def ready():
                assert native.poll() is None,native_log.read_text()
                for line in native_log.read_text().splitlines():
                    try:
                        item=json.loads(line)
                        if item.get('ready'):return item
                    except ValueError:pass
            info=wait(ready);client=NativeCompositor(info['control']);display=info['wayland_display'];display=bytes(display['Unix']).decode() if isinstance(display,dict) else display
            child=dict(env,WAYLAND_DISPLAY=display,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell',ORBIT_QT='5')
            from sway_events import request,command
            def host_view():
                def visit(node):
                    if str(node.get('name') or '').startswith('Orbit Native'):return node
                    for node in node.get('nodes',[])+node.get('floating_nodes',[]):
                        found=visit(node)
                        if found:return found
                return visit(request(4))
            host=wait(host_view);ident=int(host['id']);command(f'[con_id={ident}] floating enable;[con_id={ident}] border pixel 0;[con_id={ident}] resize set width 1040 px height 680 px;[con_id={ident}] move absolute position 20 px 20 px');time.sleep(.2)
            source=subprocess.Popen(['/usr/bin/python3','-c',SOURCE,str(ROOT),str(files)],cwd=ROOT,env=child,stdout=log,stderr=log,start_new_session=True)
            receiver=subprocess.Popen(['/usr/bin/python3','-c',RECEIVER,str(received)],cwd=ROOT,env=child,stdout=log,stderr=log,start_new_session=True)
            def app_row(title):return next((row for row in client.windows() if row['title']==title and row['rect']['width']>1),None)
            first=wait(lambda:app_row('Mellipi owned file source'));second=wait(lambda:app_row('Mellipi owned file receiver'))
            client.request('resize',id=int(first['id']),rect=dict(x=20,y=40,width=400,height=500));client.request('resize',id=int(second['id']),rect=dict(x=580,y=40,width=380,height=500));time.sleep(.3)
            pointer=VirtualPointer(outer);bounds=request(3)[0]['rect'];view=host_view();rect=view['rect'];inner=view.get('window_rect',{});output=client.snapshot()['outputs'][0]['rect'];target=(output['width']//2,output['height']//2)
            pointer.move(rect['x']+inner.get('x',0)+target[0],rect['y']+inner.get('y',0)+target[1],bounds['width'],bounds['height']);time.sleep(.1);actual=client.status()['pointer'];offset=(target[0]-actual['x'],target[1]-actual['y'])
            def move(x,y,button=None):
                view=host_view();rect=view['rect'];inner=view.get('window_rect',{})
                pointer.move(rect['x']+inner.get('x',0)+offset[0]+x,rect['y']+inner.get('y',0)+offset[1]+y,bounds['width'],bounds['height'])
                if button is not None:pointer.send(5,2,struct.pack('=III',int(time.monotonic()*1000)&0xffffffff,272,button));pointer.send(5,4);pointer.roundtrip()
                time.sleep(.08)
            move(60,80,1)
            for x,y in ((80,90),(120,110),(240,130),(400,150),(600,180),(700,200)):move(x,y)
            move(700,200,0)
            wait(received.exists,5);assert json.loads(received.read_text())==[str(fixture)];assert fixture.exists()
            print('PASS desktop URI drag reaches separate native Wayland app; source file preserved',flush=True)
            print(json.dumps(dict(private_headless_only=True,native=True,host_apps_untouched=True,file=str(fixture))))
        finally:
            if pointer:pointer.close()
            for process in (receiver,source,native,parent):stop(process)
if __name__=='__main__':main()

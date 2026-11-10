#!/usr/bin/env python3
"""Clipboard/primary protocol checks in an owned private native desktop.
No physical clipboard, desktop or application is addressed.
"""
import json,os,signal,subprocess,sys,tempfile,time,importlib.util,struct,socket
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
from native_compositor import NativeCompositor

def wait(check,seconds=15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=check()
        if result:return result
        time.sleep(.03)
    raise AssertionError('Private selection QA timed out')
def stop(p):
    if p and p.poll() is None:
        os.killpg(p.pid,signal.SIGTERM)
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=3)
FIXTURE=r'''
from PyQt5.QtWidgets import QApplication,QWidget,QLineEdit
from PyQt5.QtCore import QTimer,QMimeData
from PyQt5.QtGui import QClipboard
from pathlib import Path
import json,sys
job=json.loads(Path(sys.argv[1]).read_text());a=QApplication([]);w=QWidget();w.setWindowTitle(job['title']);w.resize(180,100);w.show();done=False
if job['operation']=='typing':
 edit=QLineEdit(w);edit.setGeometry(5,5,170,35);edit.show();edit.setFocus();Path(job['result']).write_text('');edit.textChanged.connect(lambda text:Path(job['result']).write_text(text))
mode=QClipboard.Selection if job.get('primary') else QClipboard.Clipboard
payload=job.get('payload','Abstract retained text')
def tick():
 global done
 if job['operation']=='typing' or done or not Path(job['gate']).exists():return
 if job['operation']=='write':
  if job.get('sensitive'):
   data=QMimeData();data.setText(payload);data.setData('x-kde-passwordManagerHint',b'secret');a.clipboard().setMimeData(data,mode)
  elif job.get('file'):
   data=QMimeData();data.setData('x-special/gnome-copied-files',payload.encode());data.setData('text/uri-list',payload.split('\n',1)[1].encode());data.setText('/tmp/Abstract file.txt');a.clipboard().setMimeData(data,mode)
  else:a.clipboard().setText(payload,mode)
  Path(job['result']).write_text('ready');done=True
 else:
  mime=job.get('mime','text/plain')
  data=a.clipboard().mimeData(mode)
  if data:
   raw=bytes(data.data(mime))
   if raw or job.get('expect_empty'):Path(job['result']).write_bytes(raw);done=True
  elif job.get('expect_empty'):Path(job['result']).write_bytes(b'');done=True
clock=QTimer();clock.timeout.connect(tick);clock.start(40);QTimer.singleShot(15000,a.quit);a.exec_()
'''
def main():
    parent=native=None;apps=[]
    with tempfile.TemporaryDirectory(prefix='abstract-native-selections-') as temp,open('/tmp/abstract-native-selections.log','w') as log:
        root=Path(temp);runtime=root/'runtime';runtime.mkdir(mode=0o700)
        config=root/'sway.conf';config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\nfocus_follows_mouse no\n')
        env={key:value for key,value in os.environ.items() if key not in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','DBUS_SESSION_BUS_ADDRESS')}
        env.update(XDG_RUNTIME_DIR=str(runtime),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        try:
            parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh; exec sway -c "$1"','abstract-selection-qa',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            outer=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
            child=dict(env,WAYLAND_DISPLAY=outer.name,WINIT_UNIX_BACKEND='wayland',RUST_LOG='smithay::wayland::virtual_keyboard=debug')
            native_log=Path('/tmp/abstract-native-selection-child.log')
            with native_log.open('w') as output:native=subprocess.Popen([str(ROOT/'.native-runtime/bin/orbit-compositor')],cwd=ROOT,env=child,stdout=output,stderr=output,start_new_session=True)
            def ready():
                assert native.poll() is None,native_log.read_text()
                for line in native_log.read_text().splitlines():
                    try:
                        row=json.loads(line)
                        if row.get('ready'):return row
                    except ValueError:pass
            info=wait(ready);client=NativeCompositor(info['control']);child['WAYLAND_DISPLAY']=info['wayland_display'];child['QT_QPA_PLATFORM']='wayland';child['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell'
            status=wait(lambda:client.status() if client.status().get('xdisplay') is not None else None)
            child['DISPLAY']=':'+str(status['xdisplay'])
            assert status['capabilities']['primary_selection'] and status['capabilities']['clipboard_text_retention']
            spec=importlib.util.spec_from_file_location('private_protocol_client',ROOT/'tools/qa-native-protocols.py');protocol=importlib.util.module_from_spec(spec);spec.loader.exec_module(protocol)
            probe=protocol.Client(child)
            assert 'zwp_primary_selection_device_manager_v1' in probe.globals
            assert 'zwp_virtual_keyboard_manager_v1' not in probe.globals
            assert 'zwp_input_method_manager_v2' not in probe.globals
            assert ('zwp_linux_dmabuf_v1' in probe.globals)==status['capabilities']['client_dmabuf']
            assert probe.globals['zwlr_screencopy_manager_v1'][1]==2
            if status['capabilities']['client_dmabuf']:
                manager=probe.bind('zwp_linux_dmabuf_v1',3);callback=probe.alloc();probe.send(1,0,struct.pack('=I',callback));probe.event(callback,0)
                formats=[struct.unpack('=III',data) for ident,opcode,data in probe.events if ident==manager and opcode==1]
                format=next((row for row in formats if row[0] in (0x34325241,0x34325258) and row[1:]==(0,0)),None) or next((row for row in formats if row[0] in (0x34325241,0x34325258)),None)
                assert format,'Renderer must advertise a usableRGB format'
                params=probe.alloc();probe.send(manager,1,struct.pack('=I',params))
                payload=struct.pack('=IIIII',0,0,256,format[1],format[2]);header=struct.pack('=II',params,((len(payload)+8)<<16)|1)
                with open('/dev/null','rb') as invalid:probe.sock.sendmsg([header+payload],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,struct.pack('=i',invalid.fileno()))])
                probe.send(params,2,struct.pack('=iiII',64,64,format[0],0))
                rejected=False
                while not rejected:
                    ident,opcode,data=probe.recv()
                    if ident==1 and opcode==0:
                        object_id,error=struct.unpack_from('=II',data)
                        assert object_id==params and error in (4,5,6),'Unexpected invalid-buffer error'
                        rejected=True
                    elif ident==params and opcode==1:rejected=True
                    elif ident==params and opcode==0:raise AssertionError('Invalid capture descriptor accepted')
                assert client.status()['capabilities']['client_dmabuf']
                print('PASS invalid client DMA-BUF metadata rejected without compositor exit',flush=True)
            probe.close();print('PASS primary selection and accurate screencopy/DMA-BUF globals; input injection remains private',flush=True)

            # A nonprivileged ordinary Qt process must not gain input-injection globals.
            fixture=root/'fixture.py';fixture.write_text(FIXTURE);serial=0
            def app(operation,platform='wayland',**extra):
                nonlocal serial
                serial+=1;name=f'Selection fixture {serial}';job=dict(operation=operation,title=name,gate=str(root/f'gate{serial}'),result=str(root/f'result{serial}'),**extra)
                path=root/f'job{serial}.json';path.write_text(json.dumps(job));process=subprocess.Popen(['/usr/bin/python3',str(fixture),str(path)],env=dict(child,QT_QPA_PLATFORM=platform),stdout=log,stderr=log,start_new_session=True);apps.append(process)
                row=wait(lambda:next((w for w in client.windows() if w['title']==name and w['rect']['width']>0),None));client.request('focus',id=int(row['id']));Path(job['gate']).touch();wait(lambda:Path(job['result']).exists());return process,Path(job['result'])
            def close_source(process):
                row=next((w for w in client.windows() if w['pid']==process.pid),None)
                assert row,'Source fixture window missing'
                client.request('close',id=int(row['id']));wait(lambda:process.poll() is not None)
            for platform in ('wayland','xcb'):
                payload='Abstract survives source exit '+platform+' ✓'
                writer,_=app('write',platform,payload=payload);time.sleep(.2);close_source(writer);time.sleep(.1)
                reader,result=app('read',payload=payload);assert result.read_text()==payload,result.read_bytes();stop(reader)
                print('PASS '+platform+' copied UTF8 text survives source exit',flush=True)
            writer,_=app('write',primary=True,payload='Primary selection survives focus');reader,result=app('read',primary=True)
            assert result.read_text()=='Primary selection survives focus';stop(reader);stop(writer)
            print('PASS independent Wayland primary-selection transfer',flush=True)
            payload='cut\nfile:///tmp/Abstract%20file.txt'
            writer,_=app('write',file=True,payload=payload);time.sleep(.2);close_source(writer);time.sleep(.1)
            reader,result=app('read',mime='x-special/gnome-copied-files');assert result.read_text()==payload;stop(reader)
            reader,result=app('read',mime='text/uri-list');assert result.read_text()==payload.split('\n',1)[1];stop(reader)
            print('PASS URI clipboard retains cut marker after source exit',flush=True)
            writer,_=app('write',sensitive=True,payload='Synthetic opted-out test');time.sleep(.2);close_source(writer);time.sleep(.1)
            reader,result=app('read',expect_empty=True);assert result.read_bytes()==b'';stop(reader)
            print('PASS password-manager opt-out prevents clipboard retention',flush=True)
            if Path('/usr/bin/wvkbd-mobintl').is_file():
                typer,result=app('typing')
                keyboard=subprocess.Popen(['/usr/bin/wvkbd-mobintl','-D','-H','240','-L','240'],env=dict(child,WAYLAND_DEBUG='1'),stdout=log,stderr=log,start_new_session=True);apps.append(keyboard)
                time.sleep(.5);assert keyboard.poll() is None,'Trusted keyboard failed to start'
                sway=wait(lambda:next(runtime.glob('sway-ipc*.sock'),None));os.environ['SWAYSOCK']=str(sway)
                sys.path.insert(0,str(ROOT/'tools'));from qa_wayland_input import VirtualPointer
                from sway_events import request
                outer_env=dict(env,WAYLAND_DISPLAY=outer.name,SWAYSOCK=str(sway));pointer=VirtualPointer(outer_env)
                def view():
                    def visit(node):
                        if str(node.get('name') or '').startswith('Orbit Native'):return node
                        for child in node.get('nodes',[])+node.get('floating_nodes',[]):
                            found=visit(child)
                            if found:return found
                    return visit(request(4))
                try:
                    host=wait(view);region=host['rect'];inner=host.get('window_rect',{});viewport=client.snapshot()['outputs'][0]['rect'];output=request(3)[0]['rect'];target=[viewport['width']//2,viewport['height']//2]
                    pointer.move(region['x']+inner.get('x',0)+target[0],region['y']+inner.get('y',0)+target[1],output['width'],output['height']);time.sleep(.1)
                    actual=client.status()['pointer'];offset=[target[0]-actual['x'],target[1]-actual['y']]
                    subprocess.run(['grim','/tmp/abstract-native-keyboard.png'],env=outer_env,check=True,timeout=5,stdout=log,stderr=log)
                    for row in (.25,.45,.65):
                        if result.read_text():break
                        for column in (.08,.2,.35):
                            host=view();region=host['rect'];inner=host.get('window_rect',{})
                            x=viewport['width']*column;y=viewport['height']-240+240*row
                            pointer.click(region['x']+inner.get('x',0)+offset[0]+x,region['y']+inner.get('y',0)+offset[1]+y,output['width'],output['height'])
                            if result.read_text():break
                    assert result.read_text(),'Installed Wayland keyboard did not type into native QLineEdit'
                    print('PASS trusted wvkbd typed into native app: '+repr(result.read_text()),flush=True)
                finally:pointer.close();stop(keyboard);stop(typer)

            print(json.dumps(dict(private_headless_only=True,client_dmabuf=status['capabilities']['client_dmabuf'],physical_gpu_acceptance=False)))
        finally:
            for process in apps:stop(process)
            stop(native);stop(parent)
if __name__=='__main__':main()

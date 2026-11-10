#!/usr/bin/env python3
"""Finite native protocol QA under an independent headless Sway parent.

Creates an owned temporary runtime; never connects to the user's compositor.
Lock ownership tests inject a PRIVATE synthetic presentation boundary, which
checks protocol state logic, not physical output security. DRM remains untested.
"""
import importlib.util,json,os,signal,socket,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from native_compositor import NativeCompositor
spec=importlib.util.spec_from_file_location('lockqa',ROOT/'tools/qa-native-protocols.py');lockqa=importlib.util.module_from_spec(spec);spec.loader.exec_module(lockqa)

def wait(fn,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.03)
    raise AssertionError('Private native protocol QA timed out')

def terminate(process):
    if process and process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)

def layer_fixture(client,keyboard_mode=1):
    compositor=client.bind('wl_compositor',4);surface=client.alloc();client.send(compositor,0,struct.pack('=I',surface))
    manager=client.bind('zwlr_layer_shell_v1',4);layer=client.alloc();namespace=b'orbit-private-security-qa\0'
    client.send(manager,0,struct.pack('=IIII',layer,surface,0,2)+struct.pack('=I',len(namespace))+namespace+b'\0'*(-len(namespace)%4))
    client.send(layer,0,struct.pack('=II',100,100));client.send(layer,1,struct.pack('=I',1|4));client.send(layer,4,struct.pack('=I',keyboard_mode));client.send(surface,6)
    serial,width,height=struct.unpack('=III',client.event(layer,0));client.send(layer,6,struct.pack('=I',serial))
    shm=client.bind('wl_shm',1);pool=client.alloc();buffer=client.alloc();fd=os.memfd_create('orbit-private-layer',os.MFD_CLOEXEC)
    try:
        os.write(fd,b'\x55\x77\x99\xff'*100*100);payload=struct.pack('=II',pool,40000)
        client.sock.sendmsg([struct.pack('=II',shm,((len(payload)+8)<<16))+payload],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,struct.pack('=i',fd))])
        client.send(pool,0,struct.pack('=IIIIII',buffer,0,100,100,400,0));client.send(pool,1)
    finally:os.close(fd)
    client.send(surface,1,struct.pack('=Iii',buffer,0,0));client.send(surface,2,struct.pack('=iiii',0,0,100,100));client.send(surface,6)
    return surface,layer


class Checks(list):
    def append(self,value):super().append(value);print("PASS "+value,flush=True)

def main():
    checks=Checks();parent=native=None
    binary=Path(os.environ.get('ORBIT_NATIVE_QA_BINARY',str(ROOT/'.native-runtime/bin/orbit-compositor')))
    if not binary.is_file():raise SystemExit('Build native compositor first')
    with tempfile.TemporaryDirectory(prefix='orbit-security-qa-') as temp:
        directory=Path(temp);runtime=directory/'runtime';runtime.mkdir(mode=0o700)
        config=directory/'sway.conf';config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\nfocus_follows_mouse no\n')
        env=os.environ.copy()
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','DBUS_SESSION_BUS_ADDRESS','ORBIT_NATIVE_CONTROL','ORBIT_NATIVE_NESTED_BUS'):env.pop(key,None)
        env.update(XDG_RUNTIME_DIR=str(runtime),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        try:
            with open('/tmp/orbit-security-parent.log','w') as log:
                parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh; exec sway -c "$1"','orbit-security-qa',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            parent_socket=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
            def start(test_lock,transform=None):
                environment=dict(env,WAYLAND_DISPLAY=parent_socket.name,WINIT_UNIX_BACKEND='wayland',ORBIT_NATIVE_PROFILE='economy',RUST_LOG='orbit_compositor=debug,smithay=info')
                if transform:environment['ORBIT_NATIVE_QA_TRANSFORM']=transform
                else:environment.pop('ORBIT_NATIVE_QA_TRANSFORM',None)
                if test_lock:environment['ORBIT_NATIVE_QA_LOCK']='1'
                else:environment.pop('ORBIT_NATIVE_QA_LOCK',None)
                stream=open('/tmp/orbit-security-native.log','w')
                process=subprocess.Popen([str(binary)],cwd=ROOT,env=environment,stdout=stream,stderr=stream,start_new_session=True);stream.close()
                def ready():
                    if process.poll() is not None:raise AssertionError('Private native compositor exited; see /tmp/orbit-security-native.log')
                    for line in Path('/tmp/orbit-security-native.log').read_text().splitlines():
                        try:
                            row=json.loads(line)
                            if row.get('ready'):return row
                        except ValueError:pass
                info=wait(ready);child=dict(environment,WAYLAND_DISPLAY=info['wayland_display']);child.pop('SWAYSOCK',None)
                return process,info,child
            native,info,child=start(False)
            client=lockqa.Client(child)
            assert 'ext_session_lock_manager_v1' not in client.globals,'Nested preview must defer real locking to its parent'
            assert {'zwlr_screencopy_manager_v1','ext_idle_notifier_v1','zwp_idle_inhibit_manager_v1','zwp_text_input_manager_v3'}<=set(client.globals)
            assert 'zwp_input_method_manager_v2' not in client.globals,'Untrusted clients must not bind the privileged IME manager'
            checks.append('nested lock global omitted; capture and idle protocols available')
            seat=client.bind('wl_seat',1);manager=client.bind('ext_idle_notifier_v1',2);notification=client.alloc()
            client.send(manager,2,struct.pack('=III',notification,30,seat));client.event(notification,0)
            checks.append('request-driven input-idle timer delivers idled event')
            client.send(notification,0)
            keyboard=client.alloc();client.send(seat,1,struct.pack('=I',keyboard))
            surface,layer=layer_fixture(client,1)
            entry=client.event(keyboard,1);assert struct.unpack_from('=I',entry,4)[0]==surface
            checks.append('mapped exclusive layer receives keyboard focus')
            text_manager=client.bind('zwp_text_input_manager_v3',1);text_input=client.alloc();client.send(text_manager,1,struct.pack('=II',text_input,seat))
            callback=client.alloc();client.send(1,0,struct.pack('=I',callback));client.event(callback,0)
            checks.append('standard text-input binds without installed engine; privileged IME hidden from untrusted client')
            inhibit_manager=client.bind('zwp_idle_inhibit_manager_v1',1);inhibitor=client.alloc();client.send(inhibit_manager,1,struct.pack('=II',inhibitor,surface))
            regular=client.alloc();client.send(manager,1,struct.pack('=III',regular,80,seat))
            input_idle=client.alloc();client.send(manager,2,struct.pack('=III',input_idle,120,seat));client.event(input_idle,0)
            assert not any(event[:2]==(regular,0) for event in client.events)
            checks.append('visible layer inhibits idle while input-only timer ignores inhibition')
            client.send(inhibitor,0);client.event(regular,0)
            checks.append('destroying inhibitor rearms regular idle notification')
            client.send(layer,7);client.send(surface,0);client.event(keyboard,2)
            checks.append('destroyed exclusive layer releases keyboard focus')
            source=importlib.util.spec_from_file_location('private_pointer',ROOT/'tools/qa_wayland_input.py');pointer_module=importlib.util.module_from_spec(source);source.loader.exec_module(pointer_module)
            parent_environment=dict(env,WAYLAND_DISPLAY=parent_socket.name)
            pointer=pointer_module.VirtualPointer(parent_environment)
            try:
                from sway_events import HEADER,MAGIC,receive
                parent_control=next(runtime.glob('sway-ipc.*.sock'))
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(3);connection.connect(str(parent_control));connection.sendall(HEADER.pack(MAGIC,0,4));tree=receive(connection)[1]
                def view(node):
                    if node.get('app_id')=='orbit-native':return node
                    for descendant in node.get('nodes',[])+node.get('floating_nodes',[]):
                        found=view(descendant)
                        if found:return found
                native_view=view(tree);assert native_view
                rect=native_view['rect'];inner=native_view.get('window_rect',{})
                surface,layer=layer_fixture(client,2)
                callback=client.alloc();client.send(1,0,struct.pack('=I',callback));client.event(callback,0)
                pointer.click(rect['x']+inner.get('x',0)+20,rect['y']+inner.get('y',0)+20,width=1024,height=768)
                assert struct.unpack_from('=I',client.event(keyboard,1),4)[0]==surface
                checks.append('actual private pointer click gives on-demand layer keyboard focus')
                client.send(layer,7);client.send(surface,0);client.event(keyboard,2)
            finally:pointer.close()
            client.close()
            screenshot=directory/'capture.png'
            grim=ROOT/'.wayland-runtime/usr/bin/grim'
            result=subprocess.run([str(grim),'-o','orbit-nested',str(screenshot)],env=child,capture_output=True,text=True,timeout=10)
            assert result.returncode==0,result.stderr
            assert screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
            checks.append('real grim request exports native composed framebuffer')
            NativeCompositor(info['control']).request('quit');native.wait(timeout=5);native=None
            from qt_compat import QImage
            transforms=() if os.environ.get('ORBIT_QA_SKIP_TRANSFORMS')=='1' else ('normal','90','180','270','flipped','flipped-90','flipped-180','flipped-270')
            for transform in transforms:
                print('CHECK capture transform '+transform,flush=True)
                native,info,child=start(False,transform)
                pixel_client=lockqa.Client(child);layer_fixture(pixel_client,0)
                # A display roundtrip proves buffer attach/commit reached native.
                callback=pixel_client.alloc();pixel_client.send(1,0,struct.pack('=I',callback));pixel_client.event(callback,0)
                # Let the private parent finish mapping/configuring the new nested output.
                time.sleep(.3)
                image_path=directory/('capture-'+transform+'.png')
                result=subprocess.run([str(grim),'-o','orbit-nested',str(image_path)],env=child,capture_output=True,text=True,timeout=10)
                assert result.returncode==0,(transform,result.stderr)
                image=QImage(str(image_path));assert not image.isNull()
                color=image.pixelColor(10,10)
                assert abs(color.red()-153)<3 and abs(color.green()-119)<3 and abs(color.blue()-85)<3,(transform,image.size(),color.name())
                pixel_client.close();NativeCompositor(info['control']).request('quit');native.wait(timeout=5);native=None
            if transforms:checks.append('real grim normalizes all eight native output transforms without double rotation')
            native,info,child=start(True)
            result=subprocess.run([sys.executable,str(ROOT/'tools/qa-native-protocols.py'),'--disposable-private-lock','--native-pid',str(native.pid)],env=child,capture_output=True,text=True,timeout=20)
            assert result.returncode==0,result.stdout+'\n'+result.stderr
            checks.append('PRIVATE synthetic-presentation lock ownership, rejected unlock, capture denial and locker-death fail-closed')
            status=NativeCompositor(info['control']).status();assert status['locked']
            try:NativeCompositor(info['control']).request('workspace',workspace=2)
            except RuntimeError:pass
            else:raise AssertionError('Locked IPC accepted workspace mutation')
            checks.append('locked native IPC denies window/workspace actions')
            print(json.dumps(dict(checks=checks,hardware_validated=False,physical_session_untouched=True),indent=2))
        finally:terminate(native);terminate(parent)

if __name__=='__main__':main()

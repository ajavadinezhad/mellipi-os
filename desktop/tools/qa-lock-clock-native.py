#!/usr/bin/env python3
"""Real locker presentation in an owned nested native fixture, never the host.

No password is sent or checked. Lock readiness uses the explicit PRIVATE
synthetic presentation boundary; this is UI/timer QA, not physical-lock security.
"""
import json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
from native_compositor import NativeCompositor
from qt_compat import QImage

def wait(check,seconds=15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=check()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Private lock clock QA timed out')

def stop(process):
    if process is not None and process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:return
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)

def main():
    parent=native=locker=None
    with tempfile.TemporaryDirectory(prefix='abstract-lock-clock-') as temp,open('/tmp/abstract-lock-clock-qa.log','w') as log:
        base=Path(temp);runtime=base/'runtime';runtime.mkdir(mode=0o700)
        config=base/'sway.conf';config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\nfocus_follows_mouse no\n')
        env={key:value for key,value in os.environ.items() if key not in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','DBUS_SESSION_BUS_ADDRESS')}
        env.update(XDG_RUNTIME_DIR=str(runtime),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        try:
            parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh; exec sway -c "$1"','abstract-lock-qa',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            parent_socket=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
            sway_socket=wait(lambda:next(runtime.glob('sway-ipc*.sock'),None))
            outer=dict(env,WAYLAND_DISPLAY=parent_socket.name,SWAYSOCK=str(sway_socket))
            os.environ['SWAYSOCK']=str(sway_socket)
            child_env=dict(env,WAYLAND_DISPLAY=parent_socket.name,WINIT_UNIX_BACKEND='wayland',ORBIT_NATIVE_QA_LOCK='1')
            native_log=base/'native.log'
            with native_log.open('w') as stream:native=subprocess.Popen([str(ROOT/'.native-runtime/bin/orbit-compositor')],cwd=ROOT,env=child_env,stdout=stream,stderr=stream,start_new_session=True)
            def ready():
                assert native.poll() is None,native_log.read_text()
                for line in native_log.read_text().splitlines():
                    try:
                        row=json.loads(line)
                        if row.get('ready'):return row
                    except ValueError:pass
            info=wait(ready);client=NativeCompositor(info['control'])
            from sway_events import request,command
            def native_view():
                def visit(node):
                    if str(node.get('name') or '').startswith('Orbit Native'):return node
                    for child in node.get('nodes',[])+node.get('floating_nodes',[]):
                        found=visit(child)
                        if found:return found
                return visit(request(4))
            view=wait(native_view);ident=int(view['id'])
            command(f'[con_id={ident}] floating enable; [con_id={ident}] border pixel 0; [con_id={ident}] resize set width 860 px height 640 px; [con_id={ident}] move absolute position 60 px 40 px')
            time.sleep(.3)
            display=info['wayland_display']
            if isinstance(display,dict):display=bytes(display['Unix']).decode()
            settings=base/'settings.json'
            from preferences import Preferences
            prefs=Preferences(settings);prefs.apply_theme('lavender');prefs.set('clock24',True)
            # command() builds styles/flags only. Route its real locker to the
            # owned QA native socket; no physical compositor identity is present.
            locker_env=dict(env,WAYLAND_DISPLAY=display,SWAYSOCK=str(sway_socket),ORBIT_SETTINGS_FILE=str(settings),ORBIT_LOCK_TEXTBOX='1',ORBIT_LOCK_CLOCK_24='1')
            import screen_lock
            args=screen_lock.command(locker_env,binary=str(ROOT/'.lock-runtime/bin/swaylock'))
            locker=subprocess.Popen(args,cwd=ROOT,env=locker_env,stdout=log,stderr=log,start_new_session=True)
            assert locker.wait(timeout=12)==0,'Private locker failed readiness'
            wait(lambda:client.status()['locked']);time.sleep(.4)
            def capture(label):
                region=native_view()['rect'];path=Path('/tmp/abstract-lock-live-'+label+'.png')
                subprocess.run(['grim','-g',f'{region["x"]},{region["y"]} {region["width"]}x{region["height"]}',str(path)],env=outer,check=True,timeout=5,stdout=log,stderr=log)
                image=QImage(str(path));assert not image.isNull()
                # Same clock region, excluding password and optional battery.
                crop=image.copy(image.width()//2-180,image.height()//2-160,360,110)
                return bytes(crop.constBits().asstring(crop.sizeInBytes()))
            before=capture('before');minute=int(time.time()//60);frames=client.status()['rendered_frames']
            print('PASS real Mellipi locker ready in private native fixture; no password input',flush=True)
            wait(lambda:int(time.time()//60)>minute and client.status()['rendered_frames']>frames,65)
            time.sleep(.15);after=capture('after')
            assert before!=after,'Clock pixels did not change across the minute boundary'
            assert client.status()['locked'],'Clock update must retain lock ownership'
            print('PASS live clock redrew at minute boundary, with lock ownership unchanged',flush=True)
            print(json.dumps(dict(private_headless_only=True,synthetic_presentation=True,apps_untouched=True,password_input=False,before='/tmp/abstract-lock-live-before.png',after='/tmp/abstract-lock-live-after.png')))
        finally:
            # The daemonized locker parent may have exited long ago. Stop the
            # owned native connection first; the locker then exits on disconnect.
            # Never signal a process group whose tracked leader already exited.
            stop(native);stop(locker);stop(parent)
if __name__=='__main__':main()

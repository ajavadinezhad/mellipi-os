#!/usr/bin/env python3
"""Finite live-buffer tests nested twice inside a private headless Sway session.

Never routes commands to the physical session. Solid fixtures make frame pixels,
not animation counters alone, prove the forward/backward workspace transforms.
"""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
from qt_compat import QImage
from native_compositor import NativeCompositor
spec=importlib.util.spec_from_file_location('private_native_qa',ROOT/'tools/qa-screenshots-wayland.py');qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)

def require(value,detail):
    if not value:raise AssertionError(detail)

def wait(check,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.005)
    raise AssertionError('Native compositor QA timed out')

def colored(path):
    im=QImage(str(path));require(not im.isNull(),str(path));red=[];blue=[]
    for y in range(0,im.height(),4):
        for x in range(0,im.width(),4):
            color=im.pixelColor(x,y)
            if color.red()>220 and 50<color.green()<130 and color.blue()<30:red.append(y)
            elif color.blue()>220 and color.red()<30 and 50<color.green()<130:blue.append(y)
    def summary(rows):return dict(samples=len(rows),min_y=min(rows),max_y=max(rows)) if rows else dict(samples=0)
    return dict(red=summary(red),blue=summary(blue),width=im.width(),height=im.height())

def main():
    binary=Path(os.environ.get('ORBIT_NATIVE_QA_BINARY',str(ROOT/'compositor/target/debug/orbit-compositor')));require(binary.is_file(),'Build the native compositor first')
    session=compositor=None;client=None;fixtures=[];routed=False;checks=[];frames={}
    def record(label):checks.append(label);print('PASS '+label,flush=True)
    with tempfile.TemporaryDirectory(prefix='orbit-native-qa-') as temporary,open('/tmp/orbit-native-compositor-parent.log','w') as parent_log,open('/tmp/orbit-native-compositor-child.log','w') as native_log:
        directory=Path(temporary);settings=directory/'settings.json';settings.write_text(json.dumps(dict(profile='economy',shellLayout='fold',desktopIcons=False,reducedMotion=True)))
        env={key:value for key,value in os.environ.items() if key not in ('ORBIT_NATIVE_CONTROL','SWAYSOCK','WAYLAND_DISPLAY','DISPLAY')};env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'data'),ORBIT_FOLD_DIR=str(directory),ORBIT_FOLD_STATE=str(directory/'fold.json'),ORBIT_QA='1',PULSE_SERVER='unix:'+str(directory/'no-audio'),XDG_CONFIG_HOME=str(directory/'config'))
        try:
            session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=parent_log,stderr=parent_log,start_new_session=True)
            _,parent=qa.wait(lambda:qa.native_process(settings),30);require(parent.get('ORBIT_NESTED')=='1','Private compositor is required')
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
                if key in parent:os.environ[key]=parent[key]
            routed=True;qa.wait(lambda:qa.control('status'))
            from sway_events import request,command
            native_env=dict(parent,WINIT_UNIX_BACKEND='wayland',ORBIT_NATIVE_PROFILE='balanced',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
            native_env.pop('DISPLAY',None);native_env.pop('MESA_LOADER_DRIVER_OVERRIDE',None)
            native_env.pop('ORBIT_NATIVE_REDUCED_MOTION',None)
            compositor=subprocess.Popen([str(binary)],cwd=ROOT,env=native_env,stdout=native_log,stderr=native_log,start_new_session=True)
            def ready():
                for line in Path('/tmp/orbit-native-compositor-child.log').read_text().splitlines():
                    try:
                        row=json.loads(line)
                        if row.get('ready'):return row
                    except (ValueError,AttributeError):pass
                require(compositor.poll() is None,'Native compositor exited before ready');return None
            info=wait(ready,15)
            if isinstance(info['wayland_display'],dict):info['wayland_display']=bytes(info['wayland_display']['Unix']).decode()
            client=NativeCompositor(info['control'])
            def native_view():
                def visit(node):
                    if str(node.get('name') or '').startswith('Orbit Native'):return node
                    for child in node.get('nodes',[])+node.get('floating_nodes',[]):
                        found=visit(child)
                        if found:return found
                return visit(request(4))
            try:view=qa.wait(native_view,10)
            except AssertionError:
                print(json.dumps(dict(native_status=client.status(),parent_windows=__import__('sway_events').parse_tree(request(4)))),flush=True);raise
            ident=int(view['id'])
            command(f'[con_id={ident}] floating enable; [con_id={ident}] border pixel 0; [con_id={ident}] resize set width 860 px height 640 px; [con_id={ident}] move absolute position 100 px 40 px')
            time.sleep(.4)
            def rect():return native_view()['rect']
            child=dict(parent,WAYLAND_DISPLAY=info['wayland_display'],QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
            child.pop('SWAYSOCK',None);child.pop('DISPLAY',None)
            for color in ('#ff5500','#0055ff'):
                previous={w['id'] for w in client.windows()}
                code='from PyQt5.QtWidgets import QApplication,QWidget;from PyQt5.QtCore import Qt;a=QApplication([]);w=QWidget();w.setWindowFlags(Qt.FramelessWindowHint);w.setWindowTitle("Orbit native color fixture");w.setStyleSheet("background:'+color+'");w.resize(360,240);w.show();a.exec()'
                fixture=subprocess.Popen(['/usr/bin/python3','-c',code],env=child,stdout=parent_log,stderr=parent_log);fixtures.append(fixture)
                window=wait(lambda:next((w for w in client.windows() if w['id'] not in previous),None));wait(lambda:client.status().get('window_animations',0)>0,2)
                wait(lambda:not client.status()['animating'],3)
                client.request('maximize',id=window['id'])
                wait(lambda:not client.status()['animating'],3)
                if color=='#ff5500':red=window['id']
                else:blue=window['id']
            record('first-buffer opening animations settle without changing window state')
            client.move(blue,2);time.sleep(.25)
            capture_region=rect()
            def raw_capture(label):
                region=capture_region;path=Path('/tmp/orbit-native-'+label+'.png')
                subprocess.run(['grim','-g',f'{region["x"]},{region["y"]} {region["width"]}x{region["height"]}',str(path)],env=parent,check=True,timeout=5,stdout=parent_log,stderr=parent_log)
                return path
            def capture(label):
                frames[label]=colored(raw_capture(label));return frames[label]
            before=capture('workspace-before');require(before['red']['samples']>before['width']*before['height']/32,before)
            client.request('maximize',id=red,restore=True)
            wait(lambda:client.status().get('window_animations',0)>0,2)
            # Capture raw frames first; Python pixel analysis takes longer than
            # the effect on a2-core machine and must not block its sampling.
            wait(lambda:next(w for w in client.windows() if w['id']==red)['rect']['width']==360,2)
            samples=[];captures=[]
            for index in range(5):
                path=Path('/tmp/orbit-native-window-restore-sample-'+str(index)+'.png');samples.append(path)
                region=capture_region
                captures.append(subprocess.Popen(['grim','-g',f'{region["x"]},{region["y"]} {region["width"]}x{region["height"]}',str(path)],env=parent,stdout=parent_log,stderr=parent_log))
                time.sleep(.025)
            for process in captures:require(process.wait(timeout=5)==0,'Private frame capture failed')
            analyzed=[colored(path) for path in samples]
            middle=next((frame for frame in analyzed if 360*240//16<frame['red']['samples']<before['red']['samples']),None)
            require(middle is not None,dict(samples=analyzed))
            frames['window-restore-middle']=middle
            wait(lambda:not client.status()['animating'],3);restored=capture('window-restored')
            require(restored['red']['samples']<middle['red']['samples']<before['red']['samples'],(before,middle,restored))
            require(restored['red']['samples']==360*240//16,restored)
            record('live maximize restore renders intermediate geometry and final360x240')
            client.request('minimize',id=red)
            require(next(w for w in client.windows() if w['id']==red)['minimized'],'Minimize state is immediate')
            require(client.status()['window_animations']>0,'Minimize live effect active')
            wait(lambda:not client.status()['animating'],3)
            require(capture('window-minimized')['red']['samples']==0,'Minimized window no longer rendered')
            client.request('focus',id=red)
            wait(lambda:not client.status()['animating'],3)
            require(capture('window-unminimized')['red']['samples']==restored['red']['samples'],'Restore returns same fixture geometry')
            record('minimize and restore preserve app, focus and exact final geometry')
            client.request('maximize',id=red);wait(lambda:not client.status()['animating'],3)
            # Turning reduced motion on mid-flight finishes all native effects.
            client.request('maximize',id=red,restore=True)
            wait(lambda:client.status()['window_animations']>0,2)
            client.request('motion',settings=dict(economy=True,reduced_motion=True,enabled=True))
            require(client.status()['window_animations']==0,'Reduced motion cancels active effects')
            for _ in range(3):
                client.request('minimize',id=red);client.request('focus',id=red)
                require(client.status()['window_animations']==0,'Reduced motion starts no effects')
            client.request('maximize',id=red)
            time.sleep(.1)
            client.request('motion',settings=dict(economy=False,reduced_motion=False,enabled=False))
            client.request('maximize',id=red,restore=True)
            wait(lambda:client.status()['window_animations']>0,2)
            wait(lambda:not client.status()['animating'],3)
            client.request('maximize',id=red);wait(lambda:not client.status()['animating'],3)
            record('window effects remain enabled when only workspace transitions are disabled')
            client.request('motion',settings=dict(economy=False,reduced_motion=False,enabled=True))
            record('rapid minimize/restore and reduced-motion cancellation leave no retained effects')
            def slide(target,direction,label):
                client.switch_workspace(target,direction);state=wait(lambda:(s if s['animating'] and .42<s['progress']<.65 else None) if (s:=client.status()) else None,3)
                frame=capture(label);frame['sampled_progress']=state['progress'];frame['direction']=state['direction']
                require(frame['red']['samples']>100 and frame['blue']['samples']>100,(label,frame))
                require(frame['direction']==direction,(label,frame))
                if direction>0:require(frame['red']['max_y']<frame['blue']['min_y'],frame)
                else:require(frame['blue']['min_y']>frame['red']['max_y'],frame)
                wait(lambda:not client.status()['animating'],3);require(client.status()['workspace']==target,client.status())
                record(label+' both live colors and direction')
            slide(2,1,'slide-forward');settled=capture('workspace-blue');require(settled['blue']['samples']>settled['width']*settled['height']/32,settled)
            slide(1,-1,'slide-backward');capture('workspace-red-returned')
            time.sleep(.3)
            def ticks(pid):
                fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split();return int(fields[11])+int(fields[12])
            def pss(pid):
                text=Path(f'/proc/{pid}/smaps_rollup').read_text()
                return int(next(line for line in text.splitlines() if line.startswith('Pss:')).split()[1])/1024
            began=time.monotonic();cpu_before=ticks(compositor.pid);idle_before=client.status()['rendered_frames'];time.sleep(1)
            idle_after=client.status()['rendered_frames'];elapsed=time.monotonic()-began
            metrics=dict(scope='native compositor '+binary.name+', nested software rendering; fixtures separately',seconds=round(elapsed,3),native_pss_mib=round(pss(compositor.pid),1),native_cpu_percent=round((ticks(compositor.pid)-cpu_before)/os.sysconf('SC_CLK_TCK')/elapsed*100,2),fixture_pss_mib=round(sum(pss(f.pid) for f in fixtures),1))
            require(idle_before==idle_after,(idle_before,idle_after));record('idle renderer stops between damage events')
            client.request('close',id=blue);wait(lambda:fixtures[1].poll() is not None,5);wait(lambda:len(client.windows())==1 and client.windows()[0]['id']==red,3)
            client.request('close',id=red);wait(lambda:fixtures[0].poll() is not None,5);wait(lambda:not client.windows(),3);record('native close targets owned fixtures only')
            require(not qa.control('status')['qml_errors'],qa.control('status')['qml_errors'])
            client.request('quit');compositor.wait(timeout=10);require(compositor.returncode==0,compositor.returncode);client=None
            qa.control('quit')
            try:command('exit')
            except (ConnectionError,FileNotFoundError,ConnectionRefusedError):pass
            session.wait(timeout=15);require(session.returncode==0,session.returncode)
            print(json.dumps(dict(private_headless_only=True,capture_based=False,checks=checks,frames=frames,idle_rendered_frames=idle_after,metrics=metrics),indent=2))
        finally:
            for fixture in fixtures:
                if fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
            if compositor and compositor.poll() is None:
                try:
                    if client:client.request('quit')
                    compositor.wait(timeout=3)
                except Exception:compositor.terminate();compositor.wait(timeout=3)
            if session and session.poll() is None:
                if routed:
                    try:__import__('sway_events').command('exit')
                    except Exception:pass
                try:session.wait(timeout=5)
                except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)
if __name__=='__main__':main()

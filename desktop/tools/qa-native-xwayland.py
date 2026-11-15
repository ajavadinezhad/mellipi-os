#!/usr/bin/env python3
"""X11 live-buffer tests in a compositor-owned rootless Xwayland server.

Never routes commands to the physical session. Solid fixtures make frame pixels,
not animation counters alone, prove the forward/backward workspace transforms.
"""
import importlib.util,json,os,subprocess,sys,tempfile,time,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
from qt_compat import QImage
from native_compositor import NativeCompositor
sys.path.insert(0,str(ROOT/'tools'))
from qa_wayland_input import VirtualPointer
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
    session=compositor=None;client=None;qa_pointer=None;fixtures=[];routed=False;checks=[];frames={};metrics={};idle_after=None;headers_only="--headers-only" in sys.argv
    def record(label):checks.append(label);print('PASS '+label,flush=True)
    with tempfile.TemporaryDirectory(prefix='orbit-native-x11-qa-') as temporary,open('/tmp/orbit-native-x11-parent.log','w') as parent_log,open('/tmp/orbit-native-x11-child.log','w') as native_log:
        directory=Path(temporary);settings=directory/'settings.json';settings.write_text(json.dumps(dict(profile='economy',shellLayout='fold',desktopIcons=False,reducedMotion=True)))
        env={key:value for key,value in os.environ.items() if key not in ('ORBIT_NATIVE_CONTROL','SWAYSOCK','WAYLAND_DISPLAY','DISPLAY')};env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'data'),ORBIT_FOLD_DIR=str(directory),ORBIT_FOLD_STATE=str(directory/'fold.json'),ORBIT_QA='1',PULSE_SERVER='unix:'+str(directory/'no-audio'),XDG_CONFIG_HOME=str(directory/'config'))
        try:
            session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=parent_log,stderr=parent_log,start_new_session=True)
            _,parent=qa.wait(lambda:qa.native_process(settings),30);require(parent.get('ORBIT_NESTED')=='1','Private compositor is required')
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
                if key in parent:os.environ[key]=parent[key]
            routed=True;qa.wait(lambda:qa.control('status'))
            from sway_events import request,command
            native_env=dict(parent,WINIT_UNIX_BACKEND='wayland',ORBIT_NATIVE_PROFILE='balanced',
                            ORBIT_NATIVE_WINDOW_PLACEMENT='off',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
            native_env.pop('DISPLAY',None);native_env.pop('MESA_LOADER_DRIVER_OVERRIDE',None)
            native_env.pop('ORBIT_NATIVE_REDUCED_MOTION',None)
            compositor=subprocess.Popen([str(binary)],cwd=ROOT,env=native_env,stdout=native_log,stderr=native_log,start_new_session=True)
            def ready():
                for line in Path('/tmp/orbit-native-x11-child.log').read_text().splitlines():
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
            display=wait(lambda:({'display':value} if (value:=client.status().get('xdisplay')) is not None else None),15)['display']
            child=dict(parent,DISPLAY=str(display) if str(display).startswith(':') else ':'+str(display),QT_QPA_PLATFORM='xcb')
            child.pop('SWAYSOCK',None);child.pop('WAYLAND_DISPLAY',None)
            record('private rootless Xwayland ready')
            if not headers_only:
                for color in ('#ff5500','#0055ff'):
                    previous={w['id'] for w in client.windows()}
                    code='from PyQt5.QtWidgets import QApplication,QWidget;from PyQt5.QtCore import Qt;a=QApplication([]);w=QWidget();w.setWindowFlags(Qt.FramelessWindowHint);w.setWindowTitle("Orbit isolated X11 fixture");w.setStyleSheet("background:'+color+'");w.resize(360,240);w.show();a.exec()'
                    fixture=subprocess.Popen(['/usr/bin/python3','-c',code],env=child,stdout=parent_log,stderr=parent_log);fixtures.append(fixture)
                    window=wait(lambda:next((w for w in client.windows() if w['id'] not in previous),None));client.request('maximize',id=window['id'])
                    wait(lambda:not client.status()['animating'],3)
                    if color=='#ff5500':red=window['id']
                    else:blue=window['id']
                client.move(blue,2);time.sleep(.25)
                def capture(label):
                    region=rect();path=Path('/tmp/orbit-native-'+label+'.png')
                    subprocess.run(['grim','-g',f'{region["x"]},{region["y"]} {region["width"]}x{region["height"]}',str(path)],env=parent,check=True,timeout=5,stdout=parent_log,stderr=parent_log)
                    frames[label]=colored(path);return frames[label]
                before=capture('workspace-before');require(before['red']['samples']>before['width']*before['height']/32,before)
                client.request('maximize',id=red,restore=True);wait(lambda:not client.status()['animating'],3);restored=capture('window-restored')
                require(restored['red']['samples']<before['red']['samples']*.6,(before,restored));client.request('maximize',id=red);wait(lambda:not client.status()['animating'],3)
                require(restored['red']['samples']==360*240//16,restored)
                record('X11 maximize and360x240 restore render')
                # Prime the two real client buffers before testing their transform;
                # configure acknowledgements and parent presentation are asynchronous.
                client.request('motion',settings=dict(economy=False,reduced_motion=False,enabled=False))
                client.switch_workspace(2);wait(lambda:capture('blue-prepared')['blue']['samples']>before['width']*before['height']/32,3)
                client.switch_workspace(1);wait(lambda:capture('red-prepared')['red']['samples']>before['width']*before['height']/32,3)
                client.request('motion',settings=dict(economy=False,reduced_motion=False,enabled=True))
                def slide(target,direction,label):
                    baseline=client.status();region=rect();client.switch_workspace(target,direction);attempts=[];candidate=None;raw=[];pending=[];started=time.monotonic()
                    # Queue finite captures without waiting for PNG encoding. A
                    # single grim process can outlive the 240ms transition under
                    # nested software rendering even though its image was early.
                    for index,offset in enumerate((.02,.05,.08,.11,.14,.17,.20,.23)):
                        remaining=started+offset-time.monotonic()
                        if remaining>0:time.sleep(remaining)
                        state=client.status();path=Path('/tmp/orbit-native-'+label+'-'+str(index)+'.png');began=time.monotonic()
                        process=subprocess.Popen(['grim','-g',f'{region["x"]},{region["y"]} {region["width"]}x{region["height"]}',str(path)],env=parent,stdout=parent_log,stderr=parent_log)
                        pending.append((process,path,state,began))
                    for process,path,state,began in pending:
                        require(process.wait(timeout=5)==0,'Private frame capture failed');raw.append((path,state,client.status(),time.monotonic()-began))
                    # Pixel analysis is intentionally deferred: Python/QImage work
                    # must not consume the short real animation's sampling window.
                    for path,state,after,capture_seconds in raw:
                        frame=colored(path);frame.update(sampled_progress=state['progress'],direction=direction,rendered_frames=state['rendered_frames'],animation_frames=state['animation_frames'],progress_after_capture=after['progress'],capture_seconds=round(capture_seconds,4));attempts.append(frame);frames[path.stem]=frame
                        if frame['red']['samples']>100 and frame['blue']['samples']>100:candidate=frame
                    require(candidate is not None,dict(label=label,baseline=baseline,after=client.status(),attempts=attempts))
                    require(candidate['red']['max_y']<candidate['blue']['min_y'],candidate)
                    wait(lambda:not client.status()['animating'],3);state=client.status();require(state['workspace']==target,state)
                    require(state['animation_frames']>baseline['animation_frames']+1,(baseline,state));record(label+' both live buffers in actual rendered frames')
                slide(2,1,'slide-forward');wait(lambda:capture('workspace-blue')['blue']['samples']>before['width']*before['height']/32,3)
                slide(1,-1,'slide-backward');wait(lambda:capture('workspace-red-returned')['red']['samples']>before['width']*before['height']/32,3)
                time.sleep(.3)
                def ticks(pid):
                    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split();return int(fields[11])+int(fields[12])
                def pss(pid):
                    text=Path(f'/proc/{pid}/smaps_rollup').read_text()
                    return int(next(line for line in text.splitlines() if line.startswith('Pss:')).split()[1])/1024
                began=time.monotonic();cpu_before=ticks(compositor.pid);idle_before=client.status()['rendered_frames'];time.sleep(1)
                idle_after=client.status()['rendered_frames'];elapsed=time.monotonic()-began
                metrics=dict(scope='debug native compositor, nested software rendering; fixtures separately',seconds=round(elapsed,3),native_pss_mib=round(pss(compositor.pid),1),native_cpu_percent=round((ticks(compositor.pid)-cpu_before)/os.sysconf('SC_CLK_TCK')/elapsed*100,2),fixture_pss_mib=round(sum(pss(f.pid) for f in fixtures),1))
                require(idle_before==idle_after,(idle_before,idle_after));record('idle renderer stops between damage events')
                client.request('close',id=blue);wait(lambda:fixtures[1].poll() is not None,5);wait(lambda:len(client.windows())==1 and client.windows()[0]['id']==red,3)
                client.request('close',id=red);wait(lambda:fixtures[0].poll() is not None,5);wait(lambda:not client.windows(),3);record('X11 close targets owned fixtures only')
            qa_pointer=VirtualPointer(parent);parent_output=request(3)[0]['rect']
            previous={row['id'] for row in client.windows()}
            legacy_code='from PyQt5.QtWidgets import QApplication,QWidget;a=QApplication([]);w=QWidget();w.setWindowTitle("Orbit owned legacy header fixture");w.setStyleSheet("background:#ff5500");w.resize(300,180);w.show();a.exec()'
            legacy=subprocess.Popen(['/usr/bin/python3','-c',legacy_code],env=child,stdout=parent_log,stderr=parent_log);fixtures.append(legacy)
            row=wait(lambda:next((row for row in client.snapshot()['windows'] if row['id'] not in previous and row.get('frame')),None),8);legacy_id=row['id']
            def legacy_row():return next((row for row in client.snapshot()['windows'] if row['id']==legacy_id),None)
            # Winit may draw its own client-side host frame, which Sway's
            # window_rect cannot describe. Calibrate against native pointer state.
            host=native_view();region=host['rect'];inner=host.get('window_rect',{});viewport=client.snapshot()['outputs'][0]['rect'];target=[viewport['width']//2,viewport['height']//2]
            qa_pointer.move(region['x']+inner.get('x',0)+target[0],region['y']+inner.get('y',0)+target[1],parent_output['width'],parent_output['height']);time.sleep(.12)
            actual=client.status()['pointer'];pointer_offset=[target[0]-actual['x'],target[1]-actual['y']]
            def pointer(x,y,action=None):
                view=native_view();region=view['rect'];inner=view.get('window_rect',{})
                qa_pointer.move(region['x']+inner.get('x',0)+pointer_offset[0]+x,region['y']+inner.get('y',0)+pointer_offset[1]+y,parent_output['width'],parent_output['height'])
                if action:
                    qa_pointer.send(5,2,struct.pack('=III',int(time.monotonic()*1000)&0xffffffff,272,1 if action=='press' else 0));qa_pointer.send(5,4);qa_pointer.roundtrip()
                time.sleep(.08)
            def click_button(offset):
                row=legacy_row();frame=row['frame'];pointer(frame['x']+frame['width']-offset,frame['y']+frame['height']//2,'press');pointer(frame['x']+frame['width']-offset,frame['y']+frame['height']//2,'release')
            subprocess.run(['grim','/tmp/orbit-native-header-before.png'],env=parent,check=True,timeout=5,stdout=parent_log,stderr=parent_log)
            start=legacy_row()['rect'];frame=legacy_row()['frame'];pointer(frame['x']+24,frame['y']+14,'press');pointer(frame['x']+84,frame['y']+54);pointer(frame['x']+84,frame['y']+54,'release')
            moved=wait(lambda:(row if (row:=legacy_row())['rect']['x']>start['x']+20 else None),3)
            require(moved['frame']['y']==moved['rect']['y']-28,moved);record('legacy header drag moves native scene header with X11 body')
            initial=dict(legacy_row()['rect']);frame=legacy_row()['frame'];corner=[frame['x']+2,frame['y']+2]
            pointer(*corner,'press');pointer(corner[0]-30,corner[1]-20);pointer(corner[0]-30,corner[1]-20,'release')
            resized=wait(lambda:(row if (row:=legacy_row())['rect']['width']>=initial['width']+20 and row['rect']['height']>=initial['height']+10 else None),3)['rect']
            require(abs(resized['x']+resized['width']-initial['x']-initial['width'])<=1,(initial,resized))
            require(abs(resized['y']+resized['height']-initial['y']-initial['height'])<=1,(initial,resized))
            record('legacy header corner resize preserves the opposite corner')
            click_button(48);wait(lambda:legacy_row()['maximized'],3);record('legacy compositor header maximize button')
            click_button(48);wait(lambda:not legacy_row()['maximized'],3)
            if client.status()['capabilities'].get('window_snap'):
                output=client.snapshot()['outputs'][0]
                viewport,area=output['rect'],output['workarea']
                left=viewport['x']+2
                right=viewport['x']+viewport['width']-3
                top=viewport['y']+2
                middle=(viewport['x']+viewport['width']//2,viewport['y']+viewport['height']//2)
                original=dict(legacy_row()['rect'])
                def drag(destination):
                    frame=legacy_row()['frame']
                    pointer(frame['x']+35,frame['y']+frame['height']//2,'press')
                    pointer(*destination)
                    pointer(*destination,'release')
                def tile_bounds():
                    row=legacy_row();frame=row['frame'];body=row['rect']
                    return dict(x=frame['x'],y=frame['y'],width=frame['width'],
                                height=body['y']+body['height']-frame['y'])
                client.request('window-snap',enabled=False)
                require(client.status()['window_snap_enabled'] is False,client.status())
                drag((left,middle[1]))
                require(legacy_row().get('snap') is None,legacy_row())
                client.request('resize',id=legacy_id,rect=original)
                wait(lambda:legacy_row()['rect']==original,3)
                client.request('window-snap',enabled=True)
                def preview_sample():
                    view=native_view();host_rect=view['rect'];inner=view.get('window_rect',{})
                    image_path=directory/'snap-preview.png'
                    subprocess.run(['grim',str(image_path)],env=parent,check=True,timeout=5,
                                   stdout=parent_log,stderr=parent_log)
                    image=QImage(str(image_path))
                    x=round(host_rect['x']+inner.get('x',0)+pointer_offset[0]+area['x']+area['width']//2-20)
                    y=round(host_rect['y']+inner.get('y',0)+pointer_offset[1]+area['y']+40)
                    require(0<=x<image.width() and 0<=y<image.height(),(x,y,image.size()))
                    return image.pixelColor(x,y).rgb()
                frame=legacy_row()['frame']
                pointer(frame['x']+35,frame['y']+frame['height']//2,'press')
                pointer(left+24,middle[1])
                before_preview=preview_sample()
                pointer(left,middle[1])
                wait(lambda:client.status().get('window_snap_preview') is not None,3)
                wait(lambda:preview_sample()!=before_preview,3)
                pointer(left,middle[1],'release')
                wait(lambda:legacy_row().get('snap')=='left',3)
                require(client.status().get('window_snap_preview') is None,client.status())
                half_width=area['width']//2
                require(tile_bounds()==dict(area,width=half_width),tile_bounds())
                drag((right,top))
                wait(lambda:legacy_row().get('snap')=='top-right',3)
                require(tile_bounds()==dict(area,x=area['x']+half_width,
                                            width=area['width']-half_width,
                                            height=area['height']//2),tile_bounds())
                from native_backend import NativeWindowActions
                NativeWindowActions(client=client).restore_size(int(legacy_id))
                wait(lambda:legacy_row()['rect']==original and legacy_row().get('snap') is None,3)
                drag((right,top))
                wait(lambda:legacy_row().get('snap')=='top-right',3)
                drag(middle)
                wait(lambda:legacy_row().get('snap') is None,3)
                require(all(legacy_row()['rect'][key]==original[key] for key in ('width','height')),legacy_row())
                drag((middle[0],top))
                wait(lambda:legacy_row()['maximized'],3)
                drag(middle)
                wait(lambda:not legacy_row()['maximized'],3)
                require(all(legacy_row()['rect'][key]==original[key] for key in ('width','height')),legacy_row())
                record('legacy drag snap toggle, half, quarter, maximize and restore')
                record('compositor renders the drop preview during drag')
            click_button(80);wait(lambda:legacy_row()['minimized'],3);client.request('focus',id=legacy_id);wait(lambda:not legacy_row()['minimized'] and legacy_row()['active'],3);record('legacy header minimize and typed restore retain identity')
            click_button(16);wait(lambda:legacy.poll() is not None,3);wait(lambda:legacy_row() is None,3);record('legacy compositor header close button targets fixture')
            if client.status()['capabilities'].get('window_snap'):
                wayland_env=dict(parent,WAYLAND_DISPLAY=info['wayland_display'],
                                 QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
                wayland_env.pop('DISPLAY',None)
                wayland_env.pop('SWAYSOCK',None)
                code="""from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt
class Fixture(QWidget):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            print('Wayland fixture system move:', self.windowHandle().startSystemMove(), flush=True)
app=QApplication([])
window=Fixture()
window.setWindowFlags(Qt.FramelessWindowHint)
window.setWindowTitle('Owned Wayland snap fixture')
window.resize(340,230)
window.show()
app.exec_()
"""
                fixture=subprocess.Popen(['/usr/bin/python3','-c',code],env=wayland_env,stdout=parent_log,stderr=parent_log)
                fixtures.append(fixture)
                def wayland_row():
                    return next((row for row in client.windows() if row['title']=='Owned Wayland snap fixture'),None)
                wait(wayland_row,8)
                wait(lambda:wayland_row()['active'] and not client.status()['animating'],5)
                original=wayland_row()['rect']
                pointer(original['x']+35,original['y']+20,'press')
                time.sleep(.25)
                pointer(middle[0],middle[1])
                pointer(right,middle[1])
                before_release=client.status()
                pointer(right,middle[1],'release')
                try:
                    snapped=wait(lambda:row if (row:=wayland_row()).get('snap')=='right' else None,3)
                except AssertionError as error:
                    raise AssertionError(dict(before_release=before_release['pointer'],window=wayland_row())) from error
                require(snapped['rect']==dict(area,x=area['x']+half_width,width=area['width']-half_width),snapped)
                pointer(snapped['rect']['x']+35,snapped['rect']['y']+20,'press')
                time.sleep(.25)
                pointer(middle[0]+20,middle[1]+20)
                pointer(*middle)
                pointer(*middle,'release')
                restored=wait(lambda:row if (row:=wayland_row()).get('snap') is None else None,3)
                require(all(restored['rect'][key]==original[key] for key in ('width','height')),restored)
                client.request('close',id=restored['id'])
                wait(lambda:fixture.poll() is not None,3)
                record('Wayland client-initiated move snaps and restores floating size')
            if client.status()['capabilities'].get('window_placement'):
                area=client.snapshot()['outputs'][0]['workarea']
                half_width=area['width']//2
                half_height=area['height']//2
                def open_fixture(source,env):
                    before={row['id'] for row in client.windows()}
                    process=subprocess.Popen(['/usr/bin/python3','-c',source],env=env,
                                             stdin=subprocess.PIPE,stdout=parent_log,stderr=parent_log)
                    fixtures.append(process)
                    row=wait(lambda:next((row for row in client.windows() if row['id'] not in before),None),8)
                    return process,row['id']
                def window_row(ident):
                    return next((row for row in client.windows() if row['id']==ident),None)
                def close_fixture(process,ident):
                    client.request('close',id=ident)
                    wait(lambda:process.poll() is not None and window_row(ident) is None,5)
                client.request('window-placement',layout='columns')
                require(client.status()['window_placement']=='columns',client.status())
                fixed_code=code.replace('window.resize(340,230)','window.setFixedSize(340,230)')
                process,ident=open_fixture(fixed_code,wayland_env)
                wait(lambda:(row:=window_row(ident)) and row['active'] and not client.status()['animating'],5)
                require(window_row(ident).get('snap') is None,window_row(ident))
                close_fixture(process,ident)
                placed=[]
                for zone,bounds in [
                    ('left',dict(area,width=half_width)),
                    ('right',dict(area,x=area['x']+half_width,width=area['width']-half_width)),
                ]:
                    process,ident=open_fixture(code,wayland_env)
                    placed.append((process,ident))
                    wait(lambda:(row:=window_row(ident)) and row.get('snap')==zone and row['rect']==bounds,5)
                process,ident=open_fixture(code,wayland_env)
                wait(lambda:(row:=window_row(ident)) and row['active'] and not client.status()['animating'],5)
                require(window_row(ident).get('snap') is None,window_row(ident))
                close_fixture(process,ident)
                for process,ident in placed:
                    close_fixture(process,ident)
                record('new Wayland windows fill free columns and fixed-size or overflow windows float')
                client.request('window-placement',layout='grid')
                process,ident=open_fixture(legacy_code,child)
                row=wait(lambda:row if (row:=window_row(ident)) and row.get('snap')=='top-left' and row.get('frame') else None,5)
                frame,body=row['frame'],row['rect']
                bounds=dict(x=frame['x'],y=frame['y'],width=frame['width'],
                            height=body['y']+body['height']-frame['y'])
                require(bounds==dict(area,width=half_width,height=half_height),row)
                tall_code=code.replace('window.resize(340,230)',f'window.setMinimumHeight({half_height+40})\nwindow.resize(340,230)')
                tall,tall_id=open_fixture(tall_code,wayland_env)
                wait(lambda:(row:=window_row(tall_id)) and row.get('snap')=='right' and row['rect']['height']==area['height'],5)
                client.request('window-placement',layout='main-stack')
                wait(lambda:window_row(tall_id).get('snap')=='left' and window_row(ident).get('snap')=='top-right',5)
                close_fixture(tall,tall_id)
                client.request('window-placement',layout='rows')
                wait(lambda:window_row(ident).get('snap')=='top',5)
                client.request('minimize',id=ident)
                wait(lambda:window_row(ident)['minimized'],5)
                client.request('window-placement',layout='columns')
                client.request('restore',id=ident)
                wait(lambda:window_row(ident).get('snap')=='left' and not window_row(ident)['minimized'],5)
                close_fixture(process,ident)
                record('mixed Wayland and XWayland windows reflow live across all four layouts, including tall windows')
                reopen_code=code.replace('app.exec_()', '''import sys
from PyQt5.QtCore import QSocketNotifier
commands=QSocketNotifier(sys.stdin.fileno(),QSocketNotifier.Read)
commands.activated.connect(lambda _: window.setVisible(sys.stdin.readline().strip()=='show'))
app.exec_()
''')
                for env in (wayland_env,child):
                    client.request('window-placement',layout='columns')
                    process,ident=open_fixture(reopen_code,env)
                    wait(lambda:(row:=window_row(ident)) and row.get('snap')=='left',5)
                    process.stdin.write(b'hide\n');process.stdin.flush()
                    wait(lambda:not (row:=window_row(ident)) or row.get('snap') is None,5)
                    client.request('window-placement',layout='rows')
                    process.stdin.write(b'show\n');process.stdin.flush()
                    row=wait(lambda:next((row for row in client.windows() if row.get('snap')=='top'),None),5)
                    close_fixture(process,row['id'])
                record('hidden Wayland and XWayland windows snap when shown again')
                for env in (wayland_env,child):
                    client.request('window-placement',layout='columns')
                    first,first_id=open_fixture(code,env)
                    wait(lambda:window_row(first_id).get('snap')=='left',5)
                    client.request('minimize',id=first_id)
                    second,second_id=open_fixture(code,env)
                    wait(lambda:window_row(second_id).get('snap')=='left',5)
                    client.switch_workspace(2)
                    wait(lambda:client.status()['workspace']==2 and not client.status()['animating'],5)
                    client.request('focus',id=first_id)
                    wait(lambda:window_row(first_id).get('snap')=='right',5)
                    require(window_row(second_id).get('snap')=='left',window_row(second_id))
                    close_fixture(first,first_id)
                    close_fixture(second,second_id)
                record('restoring from another workspace respects occupied tiles in both window protocols')
                client.request('window-placement',layout='columns')
                first,first_id=open_fixture(code,wayland_env)
                wait(lambda:window_row(first_id).get('snap')=='left',5)
                client.request('snap',id=first_id,side='left')
                second,second_id=open_fixture(legacy_code,child)
                wait(lambda:window_row(second_id).get('snap')=='right',5)
                require(window_row(first_id).get('snap')=='left',window_row(first_id))
                client.move(first_id,2)
                client.request('snap',id=second_id,side='left')
                client.move(second_id,2)
                wait(lambda:window_row(second_id).get('snap')=='right' and window_row(second_id)['workspace']==2,5)
                close_fixture(first,first_id)
                close_fixture(second,second_id)
                record('manual snaps reserve tiles and moving a snapped window checks its destination')
                client.request('window-placement',layout='off')
                process,ident=open_fixture(code,wayland_env)
                wait(lambda:(row:=window_row(ident)) and row['active'] and not client.status()['animating'],5)
                require(window_row(ident).get('snap') is None,window_row(ident))
                close_fixture(process,ident)
                record('Off keeps newly opened windows floating')
                if client.status()['capabilities'].get('independent_workspaces'):
                    output=client.snapshot()['outputs'][0]['name']
                    client.request('workspace-mode',independent=True)
                    first,first_id=open_fixture(code,wayland_env)
                    wait(lambda:window_row(first_id)['active'],5)
                    client.request('workspace',workspace=2,output=output)
                    wait(lambda:client.snapshot()['outputs'][0]['workspace']==1,5)
                    require(client.status()['workspace']==2,client.status())
                    require([d['id'] for d in client.snapshot()['desktops'] if d['active']]==[1],client.snapshot()['desktops'])
                    second,second_id=open_fixture(legacy_code,child)
                    wait(lambda:window_row(second_id)['workspace']==2,5)
                    client.request('focus',id=first_id)
                    wait(lambda:window_row(first_id)['active'],5)
                    require(client.snapshot()['outputs'][0]['workspace']==0,client.snapshot()['outputs'])
                    client.request('workspace-mode',independent=False)
                    close_fixture(first,first_id)
                    close_fixture(second,second_id)
                    record('per-display workspace switching preserves application workspace ownership')
                if '--telegram' in sys.argv:
                    client.request('window-placement',layout='grid')
                    profile=directory/'telegram'
                    profile.mkdir(mode=0o700)
                    telegram=subprocess.Popen(
                        ['flatpak','run','--unshare=network','--nosocket=x11','--nosocket=fallback-x11',
                         '--socket=wayland','--filesystem='+str(profile),'org.telegram.desktop',
                         '-workdir',str(profile)],
                        env=wayland_env,stdout=parent_log,stderr=parent_log)
                    fixtures.append(telegram)
                    def telegram_window():
                        require(telegram.poll() is None,'Private Telegram exited before showing a window')
                        return next((row for row in client.windows() if 'telegram' in row['klass'].lower()),None)
                    row=wait(telegram_window,15)
                    ident=row['id']
                    wait(lambda:(row:=window_row(ident)) and row.get('snap') in ('top-left','left'),5)
                    client.request('window-placement',layout='columns')
                    wait(lambda:(row:=window_row(ident)) and row.get('snap')=='left',5)
                    client.request('window-placement',layout='grid')
                    wait(lambda:(row:=window_row(ident)) and row.get('snap') in ('top-left','left'),5)
                    record('installed Telegram Flatpak tiles live with a disposable offline profile')
            require(not qa.control('status')['qml_errors'],qa.control('status')['qml_errors'])
            client.request('quit');compositor.wait(timeout=10);require(compositor.returncode==0,compositor.returncode);client=None
            qa.control('quit')
            try:command('exit')
            except (ConnectionError,FileNotFoundError,ConnectionRefusedError):pass
            session.wait(timeout=15);require(session.returncode==0,session.returncode)
            print(json.dumps(dict(private_headless_only=True,xwayland=True,capture_based=False,checks=checks,frames=frames,idle_rendered_frames=idle_after,metrics=metrics),indent=2))
        finally:
            if qa_pointer:
                try:qa_pointer.close()
                except Exception:pass
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

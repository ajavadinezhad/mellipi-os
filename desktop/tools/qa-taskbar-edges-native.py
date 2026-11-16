#!/usr/bin/env python3
"""Split-panel and three-edge taskbar QA on disposable native output. Never physical input/session."""
import importlib.util,json,os,struct,sys,subprocess,tempfile,time
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
spec=importlib.util.spec_from_file_location('native_shell_qa',ROOT/'tools/qa-native-shell.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);qa=base.qa
from native_compositor import NativeCompositor
from panel_policy import TOP_STRIP_HEIGHT,panel_rect,panel_body_origin

def verify_workspace_drag(client,parent_env,child):
    def native_view(node):
        if (node.get('name') or '').startswith('Orbit Native'):return node
        return next((view for child in node.get('nodes',[])+node.get('floating_nodes',[]) if (view:=native_view(child))),None)
    os.environ['SWAYSOCK']=parent_env['SWAYSOCK']
    try:
        host=native_view(base.sway_request(4));outer=base.sway_request(3)[0]['rect']
    finally:
        os.environ.pop('SWAYSOCK',None)
    region,inner=host['rect'],host.get('window_rect',{})
    ox=region['x']+inner.get('x',0);oy=region['y']+inner.get('y',0)
    bounds=client.snapshot()['outputs'][0]['rect']
    center_x,center_y=bounds['width']//2,bounds['height']//2
    env=dict(child,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
    app=subprocess.Popen(['/usr/bin/python3',str(SOURCE_ROOT/'mellipi_files.py')],env=env,
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        row=qa.wait(lambda:next((r for r in client.windows() if r['klass']=='mellipi-files'),None),10)
        task=qa.wait(lambda:qa.control('qa-shell-item:spineTask_mellipi-files.desktop'),5)
        dest=qa.wait(lambda:qa.control('qa-shell-item:spineWorkspace_1'),5)
        with closing(base.VirtualPointer(parent_env)) as pointer:
            pointer.move(ox+center_x,oy+center_y,outer['width'],outer['height'])
            time.sleep(.12)
            actual=client.status()['pointer']
            ox+=center_x-actual['x'];oy+=center_y-actual['y']
            def move(x,y):pointer.move(x+ox,y+oy,outer['width'],outer['height']);time.sleep(.07)
            def button(down):
                stamp=int(time.monotonic()*1000)&0xffffffff
                pointer.send(5,2,struct.pack('=III',stamp,272,down));pointer.send(5,4);pointer.roundtrip();time.sleep(.08)
            x,y=task['x']+task['width']/2,task['y']+task['height']/2
            move(x,y);button(1);move(x,y-20);move(dest['x']+dest['width']/2,dest['y']+dest['height']/2);button(0)
        qa.wait(lambda:any(w['id']==row['id'] and w['desktop']==1 for w in client.windows()),6)
        assert client.status()['workspace']==1
        print('PASS dragging a task to the fixed workspace strip moves the window without switching',flush=True)
    finally:
        base.stop(app)

def main():
    parent=native=None;checks=[]
    with tempfile.TemporaryDirectory(prefix='orbit-taskbar-edges-') as temp,open('/tmp/orbit-taskbar-edges-native.log','w') as log:
        directory=Path(temp);settings=directory/'parent.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True)))
        config=directory/'config';config.mkdir()
        env=dict(os.environ,ORBIT_QA='1',ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'parent-data'),XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','MESA_LOADER_DRIVER_OVERRIDE'):env.pop(key,None)
        try:
            parent=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],env=env,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            _,parent_env=qa.wait(lambda:qa.native_process(settings),30)
            settings=directory/'native.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True,shellLayout='fold',panelPosition='left')))
            env=dict(parent_env,ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'native-data'),ORBIT_FOLD_DIR=str(directory),ORBIT_QA='1',XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
            native=subprocess.Popen([str(ROOT/'run-native-session.sh'),'--nested'],env=env,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            initial_pid,child=qa.wait(lambda:base.process(settings),40)
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','ORBIT_NATIVE_CONTROL'):
                os.environ.pop(key,None)
                if key in child:os.environ[key]=child[key]
            client=NativeCompositor(child['ORBIT_NATIVE_CONTROL']);qa.wait(lambda:qa.control('status'),20)
            output=client.snapshot()['outputs'][0]['rect'];before={w['id'] for w in client.snapshot()['windows']}
            for edge in ('left','right','bottom','left'):
                qa.control('qa-taskbar-position:'+edge)
                expected=panel_rect(output,edge)
                def ready():
                    state=qa.control('status');bar=state['topbar_native'];area=client.snapshot()['outputs'][0]['workarea']
                    target=dict(output,y=output["y"]+TOP_STRIP_HEIGHT,height=output["height"]-TOP_STRIP_HEIGHT)
                    if edge=='left':target.update(x=output['x']+64,width=output['width']-64)
                    elif edge=='right':target.update(width=output['width']-64)
                    else:target.update(height=target['height']-64)
                    return state if bar['width']==expected['width'] and bar['height']==expected['height']-(TOP_STRIP_HEIGHT if edge in ('left','right') else 0) and area==target else None
                try:state=qa.wait(ready,10)
                except AssertionError:
                    print('EDGE DEBUG',edge,qa.control('status'),client.snapshot()['outputs'],flush=True);raise
                assert base.process(settings)[0]==initial_pid,('Shell restarted during taskbar reorientation',edge,initial_pid,base.process(settings)[0])
                assert not state['qml_errors'],state['qml_errors']
                home=qa.wait(lambda:qa.control('qa-shell-item:spineHome'),5)
                assert expected['x']<=home['x']<expected['x']+expected['width'],(edge,home,expected)
                assert output['y']+TOP_STRIP_HEIGHT<=home['y']<expected['y']+expected['height'],(edge,home,expected)
                spaces=qa.wait(lambda:qa.control('qa-shell-item:spineWorkspaceList'),5)
                assert spaces['x']<output['x']+output['width']/2 and spaces['y']<output['y']+TOP_STRIP_HEIGHT
                for name in ('spineCapture','spineControls','spineSound','spineUsage','spineNotifications'):
                    item=qa.wait(lambda:qa.control('qa-shell-item:'+name),5)
                    assert item['x']>=output['x']+output['width']/2 and item['x']+item['width']<=output['x']+output['width'],(edge,name,item)
                    assert output['y']<=item['y'] and item['y']+item['height']<=output['y']+TOP_STRIP_HEIGHT,(edge,name,item)
                top=dict(output,height=TOP_STRIP_HEIGHT)
                for panel in ('quick','music','notifications','usage','tray','screenshot'):
                    qa.control(panel);qa.wait(lambda:qa.control('status')['panel']==panel,5)
                    body=qa.wait(lambda:qa.control('qa-shell-item:panelBody'),5);origin=panel_body_origin(panel,body['width'],body['height'],output,'top',top)
                    assert abs(body['x']-origin['x'])<=1 and abs(body['y']-origin['y'])<=1,(edge,panel,body,origin)
                    assert not qa.control('status')['qml_errors'],qa.control('status')['qml_errors']
                    qa.control(panel)
                checks.append(edge);print('PASS '+edge+' taskbar native size,reserved work area, fixed strips and aligned utility panels',flush=True)
            verify_workspace_drag(client,parent_env,child)
            assert before<={w['id'] for w in client.snapshot()['windows']}
            print(json.dumps(dict(private_headless_only=True,positions=checks,qml_errors=qa.control('status')['qml_errors'])),flush=True)
        finally:
            native_log=directory/'native-data/native-session.log'
            if native_log.exists():Path('/tmp/orbit-taskbar-owned-native-session.log').write_bytes(native_log.read_bytes())
            base.stop(native);base.stop(parent)
if __name__=='__main__':main()

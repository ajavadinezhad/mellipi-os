#!/usr/bin/env python3
"""Four-edge taskbar QA on disposable native output. Never physical input/session."""
import importlib.util,json,os,sys,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
spec=importlib.util.spec_from_file_location('native_shell_qa',ROOT/'tools/qa-native-shell.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);qa=base.qa
from native_compositor import NativeCompositor
from panel_policy import panel_rect,panel_body_origin,taskbar_body_rect,panel_thickness

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
            cases=[(edge,density) for density in ('comfortable','compact','extra') for edge in ('left','right','top','bottom')]
            for edge,density in cases:
                length='fit';floating=True
                qa.control('qa-taskbar-style:fit:1:rounded');qa.control('qa-density:'+density)
                qa.control('qa-taskbar-position:'+edge)
                appearance=dict(panelPosition=edge,taskbarLength=length,taskbarFloating=floating,density=density,compact=density!='comfortable')
                expected=panel_rect(output,appearance);reserve=panel_thickness(appearance)+16
                def ready():
                    state=qa.control('status');bar=state['topbar_native'];area=client.snapshot()['outputs'][0]['workarea']
                    target=dict(output)
                    if edge=='left':target.update(x=output['x']+reserve,width=output['width']-reserve)
                    elif edge=='right':target.update(width=output['width']-reserve)
                    elif edge=='top':target.update(y=output['y']+reserve,height=output['height']-reserve)
                    else:target.update(height=output['height']-reserve)
                    return state if bar['width']==expected['width'] and bar['height']==expected['height'] and area==target else None
                try:state=qa.wait(ready,10)
                except AssertionError:
                    print('EDGE DEBUG',edge,qa.control('status'),client.snapshot()['outputs'],flush=True);raise
                assert base.process(settings)[0]==initial_pid,('Shell restarted during taskbar reorientation',edge,initial_pid,base.process(settings)[0])
                assert not state['qml_errors'],state['qml_errors']
                for name in ('spineHome','spineCapture','spineControls','spineSound','spineUsage','spineNotifications'):
                    item=qa.wait(lambda:qa.control('qa-shell-item:'+name),5)
                    assert item['x']>=expected['x'] and item['y']>=expected['y'],(edge,name,item,expected)
                    assert item['x']+item['width']<=expected['x']+expected['width']+.5 and item['y']+item['height']<=expected['y']+expected['height']+.5,(edge,name,item,expected)
                time.sleep(.2)
                for panel in ('quick','music','notifications','usage','tray','screenshot'):
                    qa.control(panel)
                    try:qa.wait(lambda:qa.control('status')['panel']==panel,5)
                    except AssertionError:
                        print('PANEL DEBUG',edge,length,floating,panel,qa.control('status'),flush=True);raise
                    body=qa.wait(lambda:qa.control('qa-shell-item:panelBody'),5);origin=panel_body_origin(panel,body['width'],body['height'],output,edge,taskbar_body_rect(output,appearance,compact=density!='comfortable'))
                    assert abs(body['x']-origin['x'])<=1 and abs(body['y']-origin['y'])<=1,(edge,panel,body,origin)
                    assert not qa.control('status')['qml_errors'],qa.control('status')['qml_errors']
                    qa.control(panel);time.sleep(.15)
                checks.append((edge,density));print('PASS '+str(checks[-1])+' workarea, same process, controls and popovers',flush=True)
            assert before<={w['id'] for w in client.snapshot()['windows']}
            print(json.dumps(dict(private_headless_only=True,positions=checks,qml_errors=qa.control('status')['qml_errors'])),flush=True)
        finally:
            native_log=directory/'native-data/native-session.log'
            if native_log.exists():Path('/tmp/orbit-taskbar-owned-native-session.log').write_bytes(native_log.read_bytes())
            base.stop(native);base.stop(parent)
if __name__=='__main__':main()

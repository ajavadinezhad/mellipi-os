#!/usr/bin/env python3
"""Finite two-output checks in an isolated compositor, never the user session."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
qa=module('multi_helpers','qa-screenshots-wayland.py');inputs=module('multi_input','qa_wayland_input.py')
def require(value,detail):
    if not value:raise AssertionError(detail)
def main():
    session=pointer=None;routed=False;checks=[]
    with tempfile.TemporaryDirectory(prefix='orbit-multi-') as temporary,open('/tmp/orbit-multi-monitor-qa.log','w') as log:
        directory=Path(temporary);(directory/'config').mkdir();(directory/'Desktop').mkdir();(directory/'Desktop'/'fixture.txt').write_text('Private desktop icon');(directory/'config'/'user-dirs.dirs').write_text('XDG_DESKTOP_DIR="'+str(directory/'Desktop')+'"\n');settings=directory/'settings.json';settings.write_text(json.dumps(dict(profile='economy',shellLayout='fold',desktopIcons=True,reducedMotion=True)))
        env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'data'),ORBIT_QA='1',PULSE_SERVER='unix:'+str(directory/'no-audio'),XDG_CONFIG_HOME=str(directory/'config'),ORBIT_FOLD_DIR=str(directory),ORBIT_FOLD_STATE=str(directory/'fold.json'))
        try:
            session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            pid,native=qa.wait(lambda:qa.native_process(settings),30);require(native.get('ORBIT_NESTED')=='1','Private compositor required')
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
                if key in native:os.environ[key]=native[key]
            routed=True;qa.wait(lambda:qa.control('status'));pointer=inputs.VirtualPointer(native)
            from sway_events import command,request
            status=lambda:qa.control('status')
            def check(label):
                require(not status()['qml_errors'],status()['qml_errors']);checks.append(label);print('PASS',label,flush=True)
            def outputs():return [o for o in request(3) if o.get('active')]
            def areas(layout):
                rows=request(1);active=outputs();require(len(active)==2,active)
                for output in active:
                    workspace=next(w for w in rows if w['name']==output['current_workspace']);rect=workspace['rect'];screen=output['rect']
                    if layout=='fold':require(rect==dict(x=screen['x']+64,y=screen['y'],width=screen['width']-64,height=screen['height']),(layout,output['name'],rect,screen))
                    else:require(rect['x']==screen['x'] and rect['width']==screen['width'] and rect['y']>screen['y'] and rect['height']<screen['height'],(layout,rect,screen))
                return True
            def stable(layout):
                qa.wait(lambda:areas(layout),8);qa.wait(lambda:len(status()['secondary_screens'])==1 and status()['secondary_screens'][0]['surfaces']==4,8)
                require(status()['shell_window_count']<=16,status()['shell_window_count']);check(layout+' reservations and bounded surfaces')
            command('create_output');qa.wait(lambda:len(outputs())==2,8);command('output HEADLESS-1 position 0 0');command('output HEADLESS-2 mode 1024x768 position 1280 0');command('output HEADLESS-1 position 0 0');time.sleep(.5);stable('fold')
            def click(output,name):
                rect=qa.wait(lambda:qa.control('qa-output-item:'+output+':'+name),5);require(rect['visible'],rect)
                pointer.click(round(rect['x']+rect['width']/2),round(rect['y']+rect['height']/2),width=2304,height=768)
            grid=qa.wait(lambda:qa.control('qa-output-item:HEADLESS-2:desktopIconsGrid'),5);require(grid['visible'] and grid['x']>=1360 and grid['y']==16,grid);check('secondary desktop icons honor Spine insets')
            pointer.click(2200,300,width=2304,height=768,button=273)
            qa.wait(lambda:status()['context_open'] and status()['selected_output']=='HEADLESS-2',5)
            require(qa.control('qa-shell-item:contextPopup')['x']>=1280,'secondary desktop menu on wrong monitor');check('secondary desktop right-click matches primary actions');qa.control('qa-close-menu')
            click('HEADLESS-2','spineControls');qa.wait(lambda:status()['panel']=='quick' and status()['selected_output']=='HEADLESS-2',8)
            require(qa.control('qa-shell-item:sheetCloseButton')['x']>=1280,status()['screen_geometry']);check('secondary click opens panel on secondary output');qa.control('quick')
            before=next(o['current_workspace'] for o in outputs() if o['name']=='HEADLESS-1')
            command('focus output HEADLESS-2; workspace number 3');time.sleep(.3)
            click('HEADLESS-2','spineWorkspace_1');qa.wait(lambda:next(o['current_workspace'] for o in outputs() if o['name']=='HEADLESS-2')=='2',8)
            require(next(o['current_workspace'] for o in outputs() if o['name']=='HEADLESS-1')==before,'secondary workspace click changed primary');check('secondary workspace click remains on its output')
            for target in ('HEADLESS-1','HEADLESS-2','HEADLESS-1','HEADLESS-2'):
                qa.control('output:'+target);qa.wait(lambda:status()['selected_output']==target,8);stable('fold')
            require(next(o['current_workspace'] for o in outputs() if o['name']=='HEADLESS-1')==before,'primary workspace changed during panel selection');check('primary swaps preserve workspace and surfaces')
            for layout in ('classic','fold','classic','fold'):
                qa.control('qa-layout-'+layout);qa.wait(lambda:status()['shell_layout']==layout,8);time.sleep(.3);stable(layout)
            command('output HEADLESS-1 disable');qa.wait(lambda:not status()['secondary_screens'],8);require(status()['shell_window_count']<=11,status()['shell_window_count']);check('removed output surfaces cleaned')
            command('output HEADLESS-1 enable');time.sleep(.5);stable('fold');check('output readdition restores secondary surfaces')
            require(qa.native_process(settings)[0]==pid,'native restarted');pointer.close();pointer=None;qa.control('quit');session.wait(timeout=15);require(session.returncode==0,session.returncode)
            print(json.dumps(dict(private_headless_only=True,checks=checks),indent=2))
        finally:
            if pointer:pointer.close()
            if session and session.poll() is None and routed:
                from sway_events import command
                try:command('exit')
                except Exception:pass
            if session and session.poll() is None:
                try:session.wait(timeout=5)
                except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)
if __name__=='__main__':main()

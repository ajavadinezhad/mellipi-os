#!/usr/bin/env python3
"""Finite integrated Spine checks, exclusively in a private headless session."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded
qa=module('fold_shell_helpers','qa-screenshots-wayland.py');inputs=module('fold_shell_input','qa_wayland_input.py')

def require(value,detail):
    if not value:raise AssertionError(detail)

def main():
    session=pointer=None;routed=False;result={'private_headless_only':True,'checks':[],'screenshots':[]}
    with tempfile.TemporaryDirectory(prefix='orbit-spine-') as temporary,open('/tmp/orbit-spine-qa.log','w') as log:
        directory=Path(temporary);files=directory/'files';files.mkdir();settings=directory/'settings.json'
        settings.write_text(json.dumps({'profile':'economy','darkLevel':'black','shellLayout':'fold','desktopIcons':False,'reducedMotion':False}))
        env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'data'),ORBIT_FOLD_DIR=str(files),ORBIT_FOLD_STATE=str(directory/'fold.json'),ORBIT_QA='1',PULSE_SERVER='unix:'+str(directory/'no-audio-server'),XDG_CONFIG_HOME=str(directory/'config'))
        try:
            session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            native_pid,native=qa.wait(lambda:qa.native_process(settings),30)
            require(native.get('ORBIT_NESTED')=='1','Refusing a non-private compositor')
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
                if key in native:os.environ[key]=native[key]
            routed=True;qa.wait(lambda:qa.control('status'));pointer=inputs.VirtualPointer(native)
            def status():return qa.control('status')
            def point(name,optional=False):
                if optional:
                    value=qa.control('qa-shell-item:'+name)
                    return value if value and value.get('visible') and value.get('width',0)>0 else None
                value=qa.wait(lambda:qa.control('qa-shell-item:'+name),5)
                require(value.get('visible') and value.get('width',0)>0 and value.get('height',0)>0,(name,value));return value
            def click(name):
                rect=point(name);screen=status()['screen_geometry']
                pointer.click(round(rect['x']+rect['width']/2),round(rect['y']+rect['height']/2),width=screen['width'],height=screen['height'])
            def capture(label):
                time.sleep(.6)
                result.setdefault('captures',{})[label]={'panel':qa.control('qa-panel-state'),'status':status()}
                destination='/tmp/orbit-spine-'+label+'.png';subprocess.run(['grim',destination],env=native,check=True,timeout=5,stdout=log,stderr=log);result['screenshots'].append(destination)
            import sway_events
            def bounded(name):
                item=point(name);screen=status()['screen_geometry']
                require(item['x']>=0 and item['y']>=0 and item['x']+item['width']<=screen['width']+1 and item['y']+item['height']<=screen['height']+1,(name,item,screen))
            def healthy(label):
                require(not status()['qml_errors'],status()['qml_errors'])
                for name in ('spineHome','spineCapture','spineSound','spineControls'):bounded(name)
                result['checks'].append(label);print('PASS',label,flush=True)
            def outside():
                screen=status()['screen_geometry'];pointer.click(screen['width']-3,screen['height']-3,width=screen['width'],height=screen['height']);qa.wait(lambda:status()['panel']=='',4)
            for width,height,mode,scale in ((1280,720,'dark',1),(1280,720,'light',1),(560,640,'dark',1),(560,640,'light',1.5)):
                sway_events.command('output HEADLESS-1 mode '+str(width)+'x'+str(height));qa.wait(lambda:status()['screen_geometry']['width']==width,5)
                qa.control('qa-'+mode);qa.control('qa-text-scale:'+str(scale));time.sleep(.3)
                label=str(width)+'-'+mode+'-'+str(scale);healthy('bounded spine '+label);capture(label+'-desktop')
                click('spineHome');qa.wait(lambda:status()['panel']=='launcher',4)
                qa.wait(lambda:qa.control('qa-fold-state')['state'].get('view')=='apps',4)
                bounded('foldAppSearch');click('foldToolsButton');qa.wait(lambda:qa.control('qa-fold-state')['state'].get('view')=='work',4)
                bounded('foldFilesLeaf');click('foldBackButton');qa.wait(lambda:qa.control('qa-fold-state')['state'].get('view')=='apps',4)
                healthy('pointer unified search and Tools '+label);capture(label+'-workboard');outside()
                for name,panel in (('spineCapture','screenshot'),('spineSound','music'),('spineNotifications','notifications'),('spineUsage','usage'),('spineControls','quick')):
                    click(name);qa.wait(lambda:status()['panel']==panel,4);bounded('sheetCloseButton');click('sheetCloseButton');qa.wait(lambda:status()['panel']=='',4)
                for panel in ('settings','system-settings','bluetooth','battery','tray'):
                    qa.control(panel);qa.wait(lambda:status()['panel']==panel,4);bounded('sheetCloseButton')
                    if panel=='system-settings':
                        for section in (1,2,3,4,5,6,7,8,9,10,11,15,0):
                            qa.control('qa-system-section:'+str(section));qa.wait(lambda:point('systemSettingsPanel').get('section')==section,4)
                    outside()
                healthy('all utility panels '+label)
                click('spineControls');qa.wait(lambda:status()['panel']=='quick',4);capture(label+'-quick');outside()
                sound=point('spineSound');pointer.move(round(sound['x']+sound['width']/2),round(sound['y']+sound['height']/2),width=width,height=height)
                tip=qa.wait(lambda:status()['tooltip'],3);require(tip['x']>=0 and tip['x']+tip['width']<=width and tip['y']>=0 and tip['y']+34<=height,tip)
                pointer.move(width-3,height-3,width=width,height=height);qa.wait(lambda:not status()['tooltip'],3)
                healthy('tooltip and outside dismissal '+label)
            result['native_pid_preserved']=qa.native_process(settings)[0]==native_pid
            require(result['native_pid_preserved'],'native restarted')
            pointer.close();pointer=None;qa.control('quit');session.wait(timeout=15);require(session.returncode==0,session.returncode)
            print(json.dumps(result,indent=2),flush=True)
        finally:
            if pointer:
                try:pointer.close()
                except Exception:pass
            if session and session.poll() is None and routed:
                import sway_events
                try:sway_events.command('exit')
                except Exception:pass
            if session and session.poll() is None:
                try:session.wait(timeout=5)
                except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)

if __name__=='__main__':main()

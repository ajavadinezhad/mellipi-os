#!/usr/bin/env python3
"""Finite whole-shell Fold checks, exclusively in a private headless session."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded
qa=module('fold_shell_helpers','qa-screenshots-wayland.py');inputs=module('fold_shell_input','qa_wayland_input.py')

def require(value,detail):
    if not value:raise AssertionError(detail)

def main():
    session=pointer=None;routed=False;result={'private_headless_only':True,'checks':[],'screenshots':[]}
    with tempfile.TemporaryDirectory(prefix='orbit-fold-shell-') as temporary,open('/tmp/orbit-fold-shell-qa.log','w') as log:
        directory=Path(temporary);files=directory/'files';files.mkdir();settings=directory/'settings.json'
        settings.write_text(json.dumps({'profile':'economy','darkLevel':'black','shellLayout':'fold','desktopIcons':False,'reducedMotion':False}))
        env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'data'),ORBIT_FOLD_DIR=str(files),ORBIT_FOLD_STATE=str(directory/'fold.json'),ORBIT_QA='1',XDG_CONFIG_HOME=str(directory/'config'))
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
            def dismiss():
                if status()['panel']:
                    screen=status()['screen_geometry'];pointer.click(20,round(screen['height']/2),width=screen['width'],height=screen['height']);qa.wait(lambda:status()['panel']=='',4)
            def check(label):
                snapshot=status();require(not snapshot['qml_errors'],snapshot['qml_errors'])
                require(snapshot['topbar_native']['height']==38,snapshot['topbar_native'])
                require(snapshot['dock_native']=={'width':811,'height':66},snapshot['dock_native'])
                require(snapshot['panel_geometry']['width']==760 and snapshot['panel_geometry']['height']==620,snapshot['panel_geometry'])
                result['checks'].append(label);print('PASS',label,flush=True)
            def fits(name):
                item=point(name);snapshot=status();panel=snapshot['panel_mask'];screen=snapshot['screen_geometry']
                if panel['height']<min(620,screen['height']-100)-1:
                    if 'contentHeight' in item and 'availableHeight' in item:
                        require(item['contentHeight']<=item['availableHeight']+1,('unnecessary scroll',name,item))
                    elif 'implicitHeight' in item:
                        require(item['height']+1>=item['implicitHeight'],('compressed panel',name,item))
            def capture(label):
                destination='/tmp/orbit-fold-shell-'+label+'.png';subprocess.run(['grim',destination],env=native,check=True,timeout=5,stdout=log,stderr=log);result['screenshots'].append(destination)
            def groups(label):
                screen=status()['screen_geometry'];left=point('foldTopLeft');clock=point('foldTopClock');right=point('foldTopRight')
                require(left['x']>=0 and left['x']+left['width']<=screen['width'],('left',left,screen))
                require(right['x']>=0 and right['x']+right['width']<=screen['width'],('right',right,screen))
                require(abs(clock['x']+clock['width']/2-screen['width']/2)<=2,('clock center',clock,screen))
                require(left['x']+left['width']<=clock['x']+1 and clock['x']+clock['width']<=right['x']+1,('group overlap',left,clock,right))
                for name in ('foldTopBrand','foldTopCamera','foldTopMusic','foldTopNotifications','foldTopUsage','foldTopSettings'):
                    item=point(name);require(item['x']>=0 and item['x']+item['width']<=screen['width']+1,(name,item,screen));require(item['y']>=0 and item['y']+item['height']<=38,(name,item))
                check(label)
            def connection_mode(connected,label):
                before={name:{key:point(name)[key] for key in ('x','y','width','height')} for name in ('foldTopLeft','foldTopClock','foldTopRight')}
                if status()['panel']!='settings':qa.control('settings')
                qa.wait(lambda:status()['panel']=='settings',4)
                appearance=point('appearancePanel');screen=status()['screen_geometry']
                pointer.click(round(appearance['x']+appearance['width']/2),round(appearance['y']+14),width=screen['width'],height=screen['height'])
                qa.wait(lambda:point('appearancePanel').get('section')==1,4)
                options=point('topbarConnectionOptions')
                pointer.click(round(options['x']+options['width']*(.75 if connected else .25)),round(options['y']+options['height']/2),width=screen['width'],height=screen['height'])
                qa.wait(lambda:status().get('topbar_connected') is connected,4)
                require(json.loads(settings.read_text()).get('topbarConnected') is connected,'Top-panel choice was not persisted')
                require(point('topbarConnectionOptions').get('value') is connected,'Appearance selector did not reflect its saved value')
                dismiss()
                strip=point('foldTopConnectedStrip',optional=True)
                if connected:
                    require(strip and abs(strip['x']-6)<=1 and abs(strip['width']-(screen['width']-12))<=1,('connected strip',strip,screen))
                else:require(strip is None,('separated strip should be hidden',strip))
                after={name:{key:point(name)[key] for key in ('x','y','width','height')} for name in before}
                require(before==after,('Top-panel mode moved controls',before,after))
                groups('Appearance '+label+' persists without moving top controls');capture(label)
            groups('Fold perimeter has left workspaces, centered clock, bounded right controls');capture('desktop-black')
            click('foldTopBrand');qa.wait(lambda:status()['panel']=='launcher',4);check('Fold brand opens the native workspace');capture('workspace-black');dismiss()
            import sway_events
            click('foldWorkspace_1');qa.wait(lambda:any(space.get('num')==2 and space.get('focused') for space in sway_events.request(1)),4)
            qa.wait(lambda:not status()['transition'].get('visible'),4)
            click('foldWorkspace_0');qa.wait(lambda:any(space.get('num')==1 and space.get('focused') for space in sway_events.request(1)),4)
            qa.wait(lambda:not status()['transition'].get('visible'),4);check('left workspace tabs switch actual compositor workspaces')
            for name,panel in (('foldTopCamera','screenshot'),('foldTopMusic','music'),('foldTopNotifications','notifications'),('foldTopUsage','usage')):
                click(name);qa.wait(lambda:status()['panel']==panel,4);check('actual '+name+' opens '+panel)
                if panel in ('screenshot','music'):fits('screenshotPanel' if panel=='screenshot' else 'musicPanel')
                click('foldPanelCloseButton');qa.wait(lambda:status()['panel']=='',4)
            optional=point('foldTopBackground',optional=True)
            if optional:
                click('foldTopBackground');qa.wait(lambda:status()['panel']=='tray',4);check('background apps opens without crash');dismiss()
            click('foldTopSettings');qa.wait(lambda:status()['panel']=='quick',4)
            for section in (1,2,0):
                rect=point('quickPanel');screen=status()['screen_geometry'];pointer.click(round(rect['x']+rect['width']*(section+.5)/3),round(rect['y']+14),width=screen['width'],height=screen['height'])
                qa.wait(lambda:point('quickPanel').get('section')==section,4);require(status()['panel']=='quick','Quick tab dismissed the panel')
            fits('quickPanel');check('actual quick-settings tab clicks preserve panel');capture('quick-black');dismiss()
            # Exercise the existing desktop menu rather than inventing an Appearance shortcut.
            screen=status()['screen_geometry'];pointer.click(30,200,width=screen['width'],height=screen['height'],button=273)
            qa.wait(lambda:status()['context_open'],4)
            menu=qa.wait(lambda:qa.control('qa-context-geometry'),4)
            pointer.click(round(menu['x']+90),round(menu['y']+6+3*32+16),width=screen['width'],height=screen['height'])
            qa.wait(lambda:status()['panel']=='settings',4);fits('appearancePanel');check('desktop right-click opens Appearance');capture('appearance-black');dismiss()
            connection_mode(True,'connected-wide-black');connection_mode(False,'separated-wide-black')
            music=point('foldTopMusic');pointer.move(round(music['x']+music['width']/2),round(music['y']+music['height']/2),width=screen['width'],height=screen['height'])
            tip=qa.wait(lambda:status()['tooltip'],3)
            require(tip['x']>=0 and tip['x']+tip['width']<=screen['width'],tip);require(tip['y']>=30 and tip['y']+34<=screen['height'],tip)
            check('top-panel tooltip stays below panel and inside output')
            pointer.move(50,350,width=screen['width'],height=screen['height']);qa.wait(lambda:not status()['tooltip'],3)
            for command,label in (('qa-light','light'),('qa-comfortable','comfortable'),('qa-dark','black-comfortable'),('qa-compact','black-compact')):
                qa.control(command);time.sleep(.2);groups('perimeter theme/layout '+label)
                if label=='light':capture('desktop-light')
            sway_events.command('output HEADLESS-1 mode 560x640');qa.wait(lambda:status()['screen_geometry']['width']==560,4);time.sleep(.2)
            groups('narrow perimeter has no overlap');capture('desktop-narrow')
            for name,panel in (('foldTopCamera','screenshot'),('foldTopMusic','music'),('foldTopNotifications','notifications'),('foldTopUsage','usage'),('foldTopSettings','quick')):
                click(name);qa.wait(lambda:status()['panel']==panel,4);click('foldPanelCloseButton');qa.wait(lambda:status()['panel']=='',4)
            check('narrow system controls and panel close remain reachable')
            qa.control('qa-comfortable');time.sleep(.2);groups('narrow comfortable perimeter remains bounded');capture('desktop-narrow-comfortable')
            connection_mode(True,'connected-narrow-black')
            qa.control('qa-light');time.sleep(.2);groups('connected narrow light perimeter remains bounded');capture('connected-narrow-light')
            connection_mode(False,'separated-narrow-light')
            if '--measure' in sys.argv:
                sway_events.command('output HEADLESS-1 mode 1280x720');qa.wait(lambda:status()['screen_geometry']['width']==1280,4)
                qa.control('qa-compact');qa.control('qa-dark');time.sleep(.5)
                metrics=module('fold_shell_metrics','qa-fold-wayland.py')
                result['idle_metrics']=metrics.idle_sample(native)
                result['idle_metrics']['scope']='Warm private 1280×720 headless Fold desktop after visiting system panels and switching themes; no app windows. Includes Sway, private bus, Orbit, Rust and active helpers. Economy/Black/compact; desktop icons disabled. Development sample, not target-PC certification.'
                (ROOT/'fold-shell-metrics.json').write_text(json.dumps(result['idle_metrics'],indent=2)+'\n')
            require(qa.native_process(settings)[0]==native_pid,'Native shell restarted during whole-shell QA')
            result['native_pid_preserved']=True;result['qml_errors']=[]
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

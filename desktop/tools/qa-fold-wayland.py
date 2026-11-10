#!/usr/bin/env python3
"""Finite Fold input/integration QA in a disposable headless Wayland desktop.

Every input target, file, note, screenshot, app and clipboard belongs to the
private test desktop. Never discovers or routes input to the physical session.
"""
import importlib.util,json,os,re,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/filename)
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded

qa=module('fold_qa_helpers','qa-screenshots-wayland.py')
inputs=module('fold_qa_input','qa_wayland_input.py')
PASTE_FIXTURE='''import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication,QTextEdit
from PyQt5.QtCore import QTimer
app=QApplication([]);app.setApplicationName('orbit-screenshot-fixture');app.setDesktopFileName('orbit-screenshot-fixture')
editor=QTextEdit();editor.setWindowTitle('Orbit disposable Fold receiver');editor.resize(360,220)
editor.textChanged.connect(lambda:Path(sys.argv[1]).write_text(editor.toPlainText(),encoding='utf-8'))
editor.show();editor.setFocus();QTimer.singleShot(120000,app.quit);app.exec()
'''

def require(condition,detail):
    if not condition:raise AssertionError(detail)

def key(pointer,code,modifiers=0):
    stamp=int(time.monotonic()*1000)&0xffffffff
    pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',modifiers,0,0,0))
    pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,code,1))
    pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,code,0))
    pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',0,0,0,0));pointer.roundtrip()

def idle_sample(native,seconds=8):
    """Measure only processes on this private bus, plus that bus's daemon."""
    address=native['DBUS_SESSION_BUS_ADDRESS']
    response=subprocess.check_output(['gdbus','call','--address',address,'--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.GetConnectionUnixProcessID','org.freedesktop.DBus'],text=True,env=native,timeout=3)
    bus_pid=int(re.search(r'uint32 (\d+)',response).group(1))
    def snapshot():
        values={}
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():continue
            try:
                entries=dict(part.split(b'=',1) for part in (process/'environ').read_bytes().split(b'\0') if b'=' in part)
                pid=int(process.name)
                if pid!=bus_pid and entries.get(b'DBUS_SESSION_BUS_ADDRESS')!=address.encode():continue
                fields=(process/'stat').read_text().rsplit(')',1)[1].split();pss=0
                for line in (process/'smaps_rollup').read_text().splitlines():
                    if line.startswith('Pss:'):pss=int(line.split()[1])/1024;break
                rss=int((process/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/1048576
                values[pid]=dict(ticks=int(fields[11])+int(fields[12]),rss=rss,pss=pss,name=(process/'comm').read_text().strip())
            except (OSError,ValueError,IndexError):pass
        return values
    before=snapshot();began=time.monotonic();samples=[]
    for _ in range(seconds):time.sleep(1);samples.append(snapshot())
    duration=time.monotonic()-began;after=samples[-1]
    cpu=sum(row['ticks']-before[pid]['ticks'] for pid,row in after.items() if pid in before)/os.sysconf('SC_CLK_TCK')/duration*100
    return dict(duration_seconds=round(duration,2),cpu_percent_one_core=round(cpu,2),pss_mib=round(sum(sum(row['pss'] for row in sample.values()) for sample in samples)/len(samples),1),summed_rss_mib=round(sum(sum(row['rss'] for row in sample.values()) for sample in samples)/len(samples),1),processes=[row['name'] for row in after.values()])

def main():
    session=fixture=pointer=None;routed=False;result={'private_headless_only':True,'checks':[]}
    with tempfile.TemporaryDirectory(prefix='orbit-fold-qa-') as temporary,open('/tmp/orbit-fold-qa.log','w') as log:
        folder=Path(temporary);files=folder/'files';files.mkdir()
        marker='NATIVE FOLD QA MESSAGE'
        (files/'00-design-note.txt').write_text(marker+'\nAn explicit local text handoff.\n')
        state_file=folder/'fold-state.json';settings=folder/'settings.json'
        settings.write_text(json.dumps({'profile':'economy','reducedMotion':not bool(os.environ.get('ORBIT_FOLD_QA_MOTION')),'desktopIcons':False,'darkLevel':'black','shellLayout':'fold'}))
        environment=os.environ.copy();environment.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(folder/'data'),ORBIT_QA='1',ORBIT_FOLD_DIR=str(files),ORBIT_FOLD_STATE=str(state_file),XDG_CONFIG_HOME=str(folder/'config'))
        try:
            session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=environment,stdout=log,stderr=log,start_new_session=True)
            native_pid,native=qa.wait(lambda:qa.native_process(settings),30)
            require(native.get('ORBIT_NESTED')=='1','Refusing non-private session')
            for name in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
                if name in native:os.environ[name]=native[name]
            routed=True;qa.wait(lambda:qa.control('status'));pointer=inputs.VirtualPointer(native)
            def status():return qa.control('status')
            def fold():return qa.control('qa-fold-state')
            def current():return fold()['state']
            def point(name):
                value=qa.wait(lambda:qa.control('qa-fold-item:'+name),4)
                require(value.get('visible',True) and value.get('width',0)>0 and value.get('height',0)>0,(name,value))
                return value
            def click(name):
                value=point(name);screen=status()['screen_geometry']
                pointer.click(round(value['x']+value['width']/2),round(value['y']+value['height']/2),width=screen['width'],height=screen['height'])
            def open_fold():
                if status()['panel'] not in ('launcher','overview'):qa.control('fold')
                qa.wait(lambda:status()['panel'] in ('launcher','overview'),4)
                if current()['view']!='work':click('foldWorkButton')
                qa.wait(lambda:current()['view']=='work',4)
            def check(label):
                snapshot=status();require(not snapshot['qml_errors'],snapshot['qml_errors']);require(snapshot['panel_geometry']['width']==760 and snapshot['panel_geometry']['height']==620,snapshot['panel_geometry'])
                dock=snapshot['dock_geometry'];mask=snapshot['dock_mask'];native_dock=snapshot['dock_native'];screen=snapshot['screen_geometry']
                require(native_dock=={'width':811,'height':66},native_dock)
                require(dock['bodyWidth']<=min(811,screen['width']-24),dock)
                require(dock['slot'] in (88,100),dock)
                require(mask['width']==dock['bodyWidth'] and mask['height']==dock['bodyHeight'],(mask,dock))
                require(mask['x']>=0 and mask['x']+mask['width']<=811 and mask['y']>=0 and mask['y']+mask['height']<=66,mask)
                require(all(isinstance(app['name'],str) and bool(app['name']) for app in snapshot['dock']),snapshot['dock'])
                panel=snapshot['panel_mask']
                panel_bottom=(screen['height']-620)/2+panel['y']+panel['height']
                dock_top=screen['height']-10-dock['bodyHeight']
                require(dock_top-panel_bottom>=8,dict(panel_bottom=panel_bottom,dock_top=dock_top,gap=dock_top-panel_bottom))
                result['checks'].append(label);print('PASS',label,flush=True)
            def capture(label):
                destination='/tmp/orbit-fold-qa-'+label+'.png'
                subprocess.run(['grim',destination],env=native,check=True,timeout=5,stdout=log,stderr=log)
                result.setdefault('screenshots',[]).append(destination)
            open_fold()
            qa.wait(lambda:fold().get('items'),8)
            require(Path(current()['folder']).resolve()==files.resolve(),current()['folder'])
            click('foldFileRow');qa.wait(lambda:current().get('selectedId'))
            click('foldCarryButton');qa.wait(lambda:current().get('carried'))
            require(marker in current()['carried'].get('body',''),current()['carried'])
            click('foldInsertButton');qa.wait(lambda:marker in current().get('noteText',''))
            require(not current().get('carried'),current())
            qa.wait(lambda:state_file.exists() and marker in state_file.read_text(),4)
            require(state_file.stat().st_mode&0o077==0,'Fold note must be private')
            check('real file carry, note insert and private atomic save');capture('work')
            fixture_environment=native.copy();fixture_environment['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell'
            pasted=folder/'receiver-note.txt'
            fixture=subprocess.Popen(['/usr/bin/python3','-c',PASTE_FIXTURE,str(pasted)],env=fixture_environment,cwd=ROOT,stdout=log,stderr=log)
            import sway_events
            view=qa.wait(lambda:next(iter(qa.fixture_windows(sway_events.request(4))),None),12)
            sway_events.command(f'[con_id={view["id"]}] move absolute position 20 px 250 px')
            open_fold();click('foldCarryButton');qa.wait(lambda:bool(current().get('carried')))
            click('foldUnfoldButton');qa.wait(lambda:current()['view']=='unfold')
            click('foldCopyFocusButton');qa.wait(lambda:status()['panel']=='',4)
            qa.wait(lambda:next(iter(qa.fixture_windows(sway_events.request(4))),{}).get('focused'),4)
            key(pointer,47,modifiers=4)  # Explicit Ctrl+V, only into this owned receiver.
            qa.wait(lambda:pasted.exists() and marker in pasted.read_text(),4)
            result['checks'].append('Copy and focus plus explicit Ctrl+V delivers text into a real app')
            open_fold();click('foldUnfoldButton');qa.wait(lambda:current()['view']=='unfold')
            check('Unfold shows real running windows');capture('unfold')
            click('foldWindowRow');qa.wait(lambda:status()['panel']=='',4)
            qa.wait(lambda:next(iter(qa.fixture_windows(sway_events.request(4))),{}).get('focused'),4)
            result['checks'].append('actual window card focuses app and folds away')
            open_fold();click('foldAppsButton');qa.wait(lambda:current()['view']=='apps');capture('apps')
            search=point('foldAppSearch');pointer.click(round(search['x']+search['width']/2),round(search['y']+search['height']/2))
            key(pointer,16);key(pointer,30)  # q, a: actual virtual-keyboard text input.
            query=qa.control('qa-fold-item:foldAppSearch')
            require(query.get('text')=='qa',query)
            check('Apps search accepts real keyboard input');capture('apps-search')
            click('foldWorkButton');qa.wait(lambda:current()['view']=='work')
            for command,label in (('qa-light','light'),('qa-dark','black'),('qa-comfortable','comfortable'),('qa-compact','compact')):
                qa.control(command);time.sleep(.18);check('theme/layout '+label)
            capture('black')
            pointer.click(100,350);qa.wait(lambda:status()['panel']=='',4)
            result['checks'].append('outside click folds away and releases input')
            open_fold();click('foldUnfoldButton');qa.wait(lambda:current()['view']=='unfold')
            minimize=qa.control('qa-fold-item:foldWindowMinimize')
            if minimize:
                click('foldWindowMinimize')
                from window_actions import find_window
                qa.wait(lambda:(found[1].get('name')=='__i3_scratch' if (found:=find_window(sway_events.request(4),view['id'])) else False),4)
                open_fold();click('foldUnfoldButton');qa.wait(lambda:current()['view']=='unfold')
                click('foldWindowRow');qa.wait(lambda:status()['panel']=='',4)
                qa.wait(lambda:(found[1].get('name')!='__i3_scratch' if (found:=find_window(sway_events.request(4),view['id'])) else False),4)
                result['checks'].append('real minimized window survives and restores from Fold')
            # Genuine narrow output, not a cosmetic QML resize; native buffers stay stable.
            sway_events.command('output HEADLESS-1 mode 560x640')
            qa.wait(lambda:status()['screen_geometry']['width']==560,4)
            open_fold();time.sleep(.25);check('narrow output stays in fixed native buffer');capture('narrow')
            sway_events.command('output HEADLESS-1 mode 1280x720')
            qa.wait(lambda:status()['screen_geometry']['width']==1280,4)
            open_fold();time.sleep(.2)
            if status()['panel']=='':open_fold()
            click('foldUnfoldButton');qa.wait(lambda:current()['view']=='unfold')
            close=qa.control('qa-fold-item:foldWindowClose')
            if close:
                click('foldWindowClose');qa.wait(lambda:not qa.fixture_windows(sway_events.request(4)),5)
                result['checks'].append('Fold close closes only disposable target')
            require(qa.native_process(settings)[0]==native_pid,'Native shell restarted during Fold QA')
            require(not status()['qml_errors'],status()['qml_errors'])
            result['native_pid_preserved']=True;result['qml_errors']=[]
            if '--measure' in sys.argv:
                open_fold();time.sleep(.8)
                result['idle_metrics']={'fold_open':idle_sample(native)}
                pointer.click(100,350);qa.wait(lambda:status()['panel']=='',4);time.sleep(.5)
                result['idle_metrics']['fold_closed']=idle_sample(native)
                result['idle_metrics']['scope']='Warm private 1280×720 headless session after disposable app closed; includes compositor, private bus, Orbit, Rust and active session helpers. Economy/Black/compact; desktop icons disabled. Summed RSS double counts shared pages. Development sample, not target-PC certification.'
                (ROOT/'fold-metrics.json').write_text(json.dumps(result['idle_metrics'],indent=2)+'\n')
            pointer.close();pointer=None;qa.control('quit');session.wait(timeout=15)
            require(session.returncode==0,session.returncode)
            print(json.dumps(result,indent=2),flush=True)
        finally:
            if pointer:
                try:pointer.close()
                except Exception:pass
            if fixture and fixture.poll() is None:
                fixture.terminate()
                try:fixture.wait(timeout=4)
                except subprocess.TimeoutExpired:fixture.kill();fixture.wait()
            if session and session.poll() is None and routed:
                import sway_events
                try:sway_events.command('exit')
                except Exception:pass
            if session and session.poll() is None:
                try:session.wait(timeout=5)
                except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)

if __name__=='__main__':main()

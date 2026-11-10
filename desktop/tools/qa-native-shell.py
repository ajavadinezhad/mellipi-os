#!/usr/bin/env python3
"""Complete Qt5 shell on native compositor under a disposable Sway parent.

No physical input, monitor, locking, app close, power or session actions. Only the
owned QWidget fixture is manipulated. Uses private settings, data, bus, Pictures.
"""
import importlib.util,json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
from native_compositor import NativeCompositor
spec=importlib.util.spec_from_file_location('native_shell_parent',ROOT/'tools/qa-screenshots-wayland.py');qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)

def process(settings):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            args=(proc/'cmdline').read_bytes().split(b'\0')
            if str(SOURCE_ROOT/'native_app.py').encode() not in args and not (b'native_app.py' in args and (proc/'cwd').resolve()==ROOT):continue
            env=dict(part.split(b'=',1) for part in (proc/'environ').read_bytes().split(b'\0') if b'=' in part)
            if env.get(b'ORBIT_SETTINGS_FILE')==str(settings).encode() and env.get(b'ORBIT_NESTED')==b'1' and b'ORBIT_NATIVE_CONTROL' in env:return int(proc.name),{k.decode():v.decode() for k,v in env.items()}
        except OSError:pass

def stop(child):
    if child and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=8)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)

def measure(root):
    def sample():
        rows={}
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():continue
            try:
                fields=(p/'stat').read_text().rsplit(')',1)[1].split();rows[int(p.name)]=(int(fields[1]),int(fields[11])+int(fields[12]))
            except (OSError,ValueError,IndexError):pass
        owned={root};last=set()
        while last!=owned:
            last=set(owned);owned.update(pid for pid,(parent,_) in rows.items() if parent in owned)
        pss=0
        for pid in owned:
            try:pss+=int(next(line.split()[1] for line in Path('/proc',str(pid),'smaps_rollup').read_text().splitlines() if line.startswith('Pss:')))
            except (OSError,StopIteration,ValueError):pass
        return {pid:rows[pid][1] for pid in owned if pid in rows},pss
    before,_=sample();began=time.monotonic();time.sleep(2);after,pss=sample();elapsed=time.monotonic()-began
    metrics=dict(scope='Native supervisor, private bus, compositor, Qt5 shell, Rust core and owned helpers; excludes disposable fixture and parent Sway',pss_MiB=round(pss/1024,1),cpu_percent_one_core=round(sum(max(0,ticks-before.get(pid,ticks)) for pid,ticks in after.items())/os.sysconf('SC_CLK_TCK')/elapsed*100,2),sample_seconds=round(elapsed,2),processes=len(after),hardware_validated=False)
    Path('/tmp/orbit-native-shell-metrics.json').write_text(json.dumps(metrics,indent=2));print('MEASURE '+json.dumps(metrics),flush=True)

def main():
    parent=native=fixture=None;parent_env=None;client=None
    with tempfile.TemporaryDirectory(prefix='orbit-native-shell-') as temp,open('/tmp/orbit-native-shell-qa.log','w') as log:
        directory=Path(temp);settings=directory/'parent.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True)))
        apps=directory/'share/applications';apps.mkdir(parents=True);(apps/'orbit-screenshot-fixture.desktop').write_text('[Desktop Entry]\nType=Application\nName=Orbit disposable fixture\nExec=/usr/bin/true\nIcon=application-x-executable\n')
        config=directory/'config';config.mkdir();(config/'user-dirs.dirs').write_text('XDG_PICTURES_DIR="'+str(directory/'pictures')+'"\n')
        env=dict(os.environ,ORBIT_QA='1',ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'parent-data'),XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'))
        try:
            parent=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            _,parent_env=qa.wait(lambda:qa.native_process(settings),30);assert parent_env['ORBIT_NESTED']=='1'
            settings=directory/'native.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=False,shellLayout='fold')))
            env=dict(parent_env,QT_LINUX_ACCESSIBILITY_ALWAYS_ON='1',XDG_DATA_HOME=str(apps.parent),ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'native-data'),ORBIT_FOLD_DIR=str(directory),ORBIT_QA='1',XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'))
            native=subprocess.Popen([str(ROOT/'run-native-session.sh'),'--nested'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            _,child=qa.wait(lambda:process(settings),40)
            assert not child.get('SWAYSOCK') and child.get('ORBIT_QT')=='5'
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','ORBIT_NATIVE_CONTROL'):
                os.environ.pop(key,None)
                if key in child:os.environ[key]=child[key]
            status=qa.wait(lambda:qa.control('status'),20);assert not status['qml_errors'],status['qml_errors']
            client=NativeCompositor(child['ORBIT_NATIVE_CONTROL']);assert client.status()['capabilities']['native_workspace_slide']
            print('PASS native Qt5 shell ready with isolated bus and no Sway IPC',flush=True)
            qa.control('launcher')
            bounds=client.snapshot()['outputs'][0]['rect']
            def centered_launcher():
                body=qa.control('qa-shell-item:panelBody')
                return body if body and abs(body['x']+body['width']/2-bounds['x']-bounds['width']/2)<=1 and abs(body['y']+body['height']/2-bounds['y']-bounds['height']/2)<=1 else None
            qa.wait(centered_launcher)
            print('PASS launcher body is centered on the native output',flush=True)
            accessible=subprocess.run(['/usr/bin/python3',str(ROOT/'tools/qa-atspi-private.py')],env=dict(child),capture_output=True,text=True,timeout=15)
            if accessible.returncode:raise AssertionError('Private AT-SPI tree check: '+accessible.stderr[-600:]+accessible.stdout[-600:])
            print('PASS Qt5 shell exports its launcher through real AT-SPI',flush=True)
            qa.control('launcher')
            fixture_env=dict(child,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
            fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=fixture_env,stdout=log,stderr=log,start_new_session=True)
            row=qa.wait(lambda:next((w for w in client.snapshot()['windows'] if w['klass']=='orbit-screenshot-fixture'),None),12);ident=int(row['id'])
            client.request('maximize',id=ident);time.sleep(.3);rect=client.snapshot()['windows'][0]['rect']
            for panel in ('launcher','quick','music','notifications','screenshot','usage','system-settings'):
                qa.control(panel);qa.wait(lambda:qa.control('status')['panel']==panel)
                state=qa.control('status');assert not state['qml_errors'],state['qml_errors']
                assert next(w for w in client.snapshot()['windows'] if int(w['id'])==ident)['rect']==rect,panel
                qa.control(panel)
            print('PASS utility sheets and menus preserve maximized client geometry',flush=True)
            qa.control('system-settings');qa.wait(lambda:qa.control('qa-shell-item:systemSettingsPanel'))
            qa.control('qa-system-section:8');qa.wait(lambda:qa.control('qa-shell-item:systemSettingsPanel').get('section')==8)
            qa.control('qa-settings-dismiss');qa.wait(lambda:qa.control('qa-shell-item:spineTask_orbit-settings'))
            qa.control('qa-settings-resume');qa.wait(lambda:(qa.control('qa-shell-item:systemSettingsPanel') or {}).get('section')==8)
            qa.control('qa-settings-close');qa.wait(lambda:not qa.control('qa-shell-item:spineTask_orbit-settings'))
            print('PASS Settings task survives dismissal and restores its Sound page',flush=True)
            client.request('minimize',id=ident);qa.wait(lambda:next(w for w in client.snapshot()['windows'] if int(w['id'])==ident)['minimized'])
            client.request('restore',id=ident);qa.wait(lambda:not next(w for w in client.snapshot()['windows'] if int(w['id'])==ident)['minimized'])
            print('PASS native minimize/restore keeps the same application alive',flush=True)
            client.request('maximize',id=ident,restore=True);time.sleep(.2);original=next(w for w in client.snapshot()['windows'] if int(w['id'])==ident)['rect']
            qa.control('qa-arrangement-save');qa.wait(lambda:len(qa.control('qa-arrangement-state')['layouts'])==1,10)
            qa.control('qa-arrangement-snap:'+str(ident)+':left');qa.wait(lambda:qa.control('qa-arrangement-state')['undo'])
            qa.control('qa-arrangement-undo');qa.wait(lambda:not qa.control('qa-arrangement-state')['busy']);qa.wait(lambda:next(w for w in client.snapshot()['windows'] if int(w['id'])==ident)['rect']==original)
            client.request('resize',id=ident,rect=dict(original,x=original['x']+24,y=original['y']+12));time.sleep(.2)
            qa.control('qa-arrangement-preview');qa.wait(lambda:qa.control('qa-arrangement-state')['preview'].get('rows'))
            assert qa.control('qa-arrangement-state')['preview']['rows'][0]['selected']==str(ident)
            qa.control('qa-arrangement-apply');qa.wait(lambda:not qa.control('qa-arrangement-state')['busy']);qa.wait(lambda:next(w for w in client.snapshot()['windows'] if int(w['id'])==ident)['rect']==original)
            assert fixture.poll() is None
            print('PASS shell arrangement undo and saved layout reuse on native IPC',flush=True)
            qa.control('qa-shot-screen');result=qa.wait(lambda:(s if not s['screenshots']['busy'] and s['screenshots'].get('lastPath') else None) if (s:=qa.control('status')) else None,15)
            path=Path(result['screenshots']['lastPath']);assert path.is_file() and directory in path.parents;assert result['screenshots']['copyToClipboard']
            print('PASS built-in screenshot uses native screencopy and private destination',flush=True)
            client.switch_workspace(2,1);qa.wait(lambda:client.status()['workspace']==2 and not client.status()['animating']);client.switch_workspace(1,-1);qa.wait(lambda:client.status()['workspace']==1 and not client.status()['animating'])
            assert fixture.poll() is None;assert not qa.control('status')['qml_errors']
            print('PASS native forward/back slides with live shell and application',flush=True)
            measure(native.pid)
        finally:
            stop(fixture)
            if client:
                try:client.request('quit')
                except Exception:pass
            stop(native)
            if parent_env:
                os.environ['SWAYSOCK']=parent_env['SWAYSOCK']
                try:
                    from sway_events import command
                    command('exit')
                except Exception:pass
            stop(parent)
if __name__=='__main__':main()

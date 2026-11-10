#!/usr/bin/env python3
"""Exercise arrangement undo/layout reuse only in a disposable headless session."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from arrangements import ArrangementEngine
from window_actions import WindowActions,find_window
from sway_events import request,command
spec=importlib.util.spec_from_file_location('arrangement_qa',ROOT/'tools/qa-screenshots-wayland.py');qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)

def main():
    session=fixture=None
    with tempfile.TemporaryDirectory(prefix='orbit-arrangement-qa-') as temp,open('/tmp/orbit-arrangement-private.log','w') as log:
        directory=Path(temp);settings=directory/'settings.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True)))
        env=dict(os.environ,ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'data'),ORBIT_QA='1',XDG_CONFIG_HOME=str(directory/'config'),PULSE_SERVER='unix:'+str(directory/'no-audio'))
        try:
            session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            _,native=qa.wait(lambda:qa.native_process(settings),30);assert native['ORBIT_NESTED']=='1'
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
                if key in native:os.environ[key]=native[key]
            qa.wait(lambda:qa.control('status'));child=dict(native,QT_QPA_PLATFORM='wayland');child.pop('QT_WAYLAND_SHELL_INTEGRATION',None)
            fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=child,stdout=log,stderr=log)
            ident=qa.wait(lambda:next((n['id'] for n in qa.fixture_windows(request(4))),None),10)
            command(f'[con_id={ident}] floating enable; [con_id={ident}] resize set width 420 px height 280 px; [con_id={ident}] move absolute position 120 px 100 px');time.sleep(.3)
            actions=WindowActions();engine=ArrangementEngine(actions,directory/'layouts.json');original=dict(find_window(request(4),ident)[0]['_outer_rect'])
            engine.record_action('Snap left',lambda:actions.snap(ident,'left'),[ident]);qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']!=original)
            assert engine.undo()['applied']==1;qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']==original)
            print('PASS real snap and exact undo',flush=True)
            engine.save('Fixture',{str(ident):'fixture.desktop'});actions.snap(ident,'right');time.sleep(.2)
            live=[dict(id=str(ident),title='Fixture',appId='fixture.desktop')];preview=engine.preview(engine.layouts[0]['id'],live,[dict(id='fixture.desktop',name='Fixture')]);assert preview['rows'][0]['selected']==str(ident)
            assert engine.apply(preview)['applied']==1;qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']==original)
            assert fixture.poll() is None;assert len(qa.fixture_windows(request(4)))==1
            print('PASS saved layout reuses the same live application',flush=True)
            saved=json.loads((directory/'layouts.json').read_text());assert 'title' not in saved['layouts'][0]['windows'][0]
            print('PASS private metadata persistence without document titles',flush=True)
        finally:
            if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=5)
            if session and session.poll() is None:
                try:command('exit')
                except Exception:session.terminate()
                try:session.wait(timeout=10)
                except subprocess.TimeoutExpired:session.kill();session.wait(timeout=5)
if __name__=='__main__':main()

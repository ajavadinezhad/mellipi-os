"""Private regression for floating maximized titles slipping beneath the top panel."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('qa',ROOT/'tools/qa-screenshots-wayland.py');qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)
from sway_events import request,command
from window_actions import WindowActions,find_window
session=fixture=None;native=None
with tempfile.TemporaryDirectory(prefix='orbit-workarea-') as temporary,open('/tmp/orbit-workarea-qa.log','w') as log:
    settings=Path(temporary)/'settings.json';settings.write_text(json.dumps({'profile':'economy','reducedMotion':True,'desktopIcons':False}))
    env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temporary+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=temporary+'/config')
    try:
        session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        _,native=qa.wait(lambda:qa.native_process(settings),30)
        assert native['ORBIT_NESTED']=='1'
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
            if key in native:os.environ[key]=native[key]
        qa.wait(lambda:qa.control('status'))
        child=native.copy();child['QT_QPA_PLATFORM']='wayland';child.pop('QT_WAYLAND_SHELL_INTEGRATION',None)
        fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=child,stdout=log,stderr=log)
        ident=qa.wait(lambda:next((n['id'] for n in qa.fixture_windows(request(4))),None),10)
        actions=WindowActions();actions.maximize(ident,True)
        _,workspace=find_window(request(4),ident);area=workspace['rect']
        qa.wait(lambda:qa.control('status')['frame_controls'].get('id')==str(ident),5)
        time.sleep(.4)
        print('INITIAL',find_window(request(4),ident)[0]['_outer_rect'],area,flush=True)
        for offset in (12,8,20):
            command(f'[con_id={ident}] move absolute position {area["x"]} px {area["y"]-offset} px')
            try:qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']==area,5)
            except AssertionError:
                print('FAILED',offset,find_window(request(4),ident)[0],qa.control('qa-window-state'),qa.control('status')['qml_errors'],flush=True);raise
        actions.maximize(ident,False)
        command(f'[con_id={ident}] resize set width 500 px height 300 px; [con_id={ident}] move absolute position 100 px 18 px')
        time.sleep(.5)
        ordinary=find_window(request(4),ident)[0]['_outer_rect'];assert ordinary['x']==100 and ordinary['y']==18,ordinary
        status=qa.control('status');assert not status['qml_errors'],status['qml_errors']
        print(json.dumps({'private_headless_only':True,'clipped_maximized_positions_repaired':3,'normal_window_position_preserved':True,'qml_errors':[]}))
        qa.control('quit');session.wait(timeout=12)
    finally:
        if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
        if session and session.poll() is None and native:
            try:command('exit')
            except Exception:pass
        if session and session.poll() is None:session.terminate();session.wait(timeout=5)

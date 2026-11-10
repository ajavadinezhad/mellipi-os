"""Private snap/bounds/shortcut checks with owned windows and no real audio."""
import importlib.util,json,os,socket,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from qt_compat import QApplication
from window_actions import WindowActions,find_window
from shortcut_settings import ShortcutSettings,config_lines
from input_settings import InputSettings
from sway_events import request,command,HEADER,MAGIC,receive
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
qa=load('window_shortcut_qa','qa-screenshots-wayland.py');inputs=load('window_shortcut_inputs','qa_wayland_input.py')
app=QApplication([]);session=fixture=native=pointer=subscription=shortcuts=input_settings=None
with tempfile.TemporaryDirectory(prefix='orbit-window-shortcuts-') as temporary,open('/tmp/orbit-window-shortcuts.log','w') as log:
    settings=Path(temporary)/'settings.json';settings.write_text(json.dumps({'profile':'economy','reducedMotion':True,'desktopIcons':False}))
    env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temporary+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=temporary+'/config',PULSE_SERVER='unix:'+temporary+'/no-audio')
    try:
        session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        _,native=qa.wait(lambda:qa.native_process(settings),30);assert native['ORBIT_NESTED']=='1'
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
            if key in native:os.environ[key]=native[key]
        qa.wait(lambda:qa.control('status'));child=native.copy();child['QT_QPA_PLATFORM']='wayland';child.pop('QT_WAYLAND_SHELL_INTEGRATION',None)
        fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=child,stdout=log,stderr=log)
        ident=qa.wait(lambda:next((n['id'] for n in qa.fixture_windows(request(4))),None),10)
        command(f'[con_id={ident}] resize set width 500 px height 300 px; [con_id={ident}] move absolute position 100 px 120 px');time.sleep(.4)
        node,space=find_window(request(4),ident);original=dict(node['_outer_rect']);area=space['rect'];actions=WindowActions()
        for side in ('left','right'):
            actions.snap(ident,side);target=dict(x=area['x']+(area['width']//2 if side=='right' else 0),y=area['y'],width=area['width']//2,height=area['height'])
            qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']==target,5)
        actions.restore_size(ident);qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']==original,5)
        print('PASS snap left/right and exact pre-snap restore',flush=True)
        # Enlarge by exactly the title/border overshoot seen in the real CSD bug.
        command(f'[con_id={ident}] resize set width {area["width"]+2} px height {area["height"]+26} px; [con_id={ident}] move absolute position -1 px {area["y"]-26} px')
        qa.wait(lambda:find_window(request(4),ident)[0]['_outer_rect']==area,5)
        print('PASS title/border overshoot repaired to complete workarea',flush=True)
        for line in config_lines():command(line)
        shortcuts=ShortcutSettings(path=Path(temporary)/'data/shortcuts.conf',command=command)
        shortcuts.setBinding('volume-up','Ctrl+Alt+Page_Up')
        until=time.monotonic()+5
        while shortcuts.busy and time.monotonic()<until:app.processEvents();time.sleep(.01)
        assert not shortcuts.busy and not shortcuts.error,shortcuts.state
        subscription=socket.socket(socket.AF_UNIX);subscription.settimeout(4);subscription.connect(os.environ['SWAYSOCK'])
        payload=b'["binding"]';subscription.sendall(HEADER.pack(MAGIC,len(payload),2)+payload);receive(subscription)
        pointer=inputs.VirtualPointer(native);stamp=int(time.monotonic()*1000)&0xffffffff
        pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',12,0,0,0))
        pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,104,1));pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,104,0))
        pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',0,0,0,0));pointer.roundtrip()
        _,event=receive(subscription);assert event['binding']['command']=='nop orbit-action-volume-up',event
        assert 'Ctrl+Mod1+Page_Up nop orbit-action-volume-up' in shortcuts.path.read_text()
        print('PASS configurable fallback produces actual compositor action',flush=True)
        input_settings=InputSettings(path=Path(temporary)/'data/input.conf',command=command,request=request)
        def settle_input():
            until=time.monotonic()+5
            while (input_settings.busy or input_settings._reading) and time.monotonic()<until:app.processEvents();time.sleep(.01)
            assert not input_settings.busy and not input_settings._reading and not input_settings.error,input_settings.state
        settle_input();keyboard=next(d for d in input_settings.devices if d['type']=='keyboard')
        input_settings.selectDevice(keyboard['identifier']);settle_input();input_settings.setLayoutList('us,de');settle_input()
        input_settings.nextLayout();settle_input()
        assert input_settings.state['layout']=='de' and input_settings.state['layoutList']=='us,de',input_settings.state
        assert 'input type:keyboard xkb_layout' not in input_settings.path.read_text()
        print('PASS selected-device layouts persist and actual keyboard cycle selects German',flush=True)
        assert not qa.control('status')['qml_errors'],qa.control('status')['qml_errors']
        pointer.close();pointer=None;subscription.close();subscription=None;shortcuts.close();shortcuts=None;input_settings.close();input_settings=None
        qa.control('quit');session.wait(timeout=15)
        print(json.dumps({'private_headless_only':True,'checks':4,'qml_errors':[]}))
    finally:
        if pointer:pointer.close()
        if subscription:subscription.close()
        if shortcuts:shortcuts.close()
        if input_settings:input_settings.close()
        if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
        if session and session.poll() is None and native:
            try:command('exit')
            except Exception:pass
        if session and session.poll() is None:session.terminate();session.wait(timeout=5)

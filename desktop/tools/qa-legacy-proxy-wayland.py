"""Private GTK XEmbed registration/removal; optional --activation tests GTK delivery."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
qa=load('legacy_qa','qa-screenshots-wayland.py');inputs=load('legacy_inputs','qa_wayland_input.py')
from qt_compat import QApplication
from sway_events import command
session=fixture=pointer=native=None
with tempfile.TemporaryDirectory(prefix='orbit-legacy-proxy-') as temp,open('/tmp/orbit-legacy-proxy.log','w') as log,open('/tmp/orbit-xembed-fixture.log','w') as fixture_log:
    settings=Path(temp)/'settings.json';settings.write_text(json.dumps(dict(profile='economy',reducedMotion=True,desktopIcons=False)))
    env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temp+'/data',ORBIT_QA='1',ORBIT_QA_LEGACY_LOG='/tmp/orbit-xembed-proxy-debug.log',XDG_CONFIG_HOME=temp+'/config')
    try:
        session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        _,native=qa.wait(lambda:qa.native_process(settings),30);assert native['ORBIT_NESTED']=='1'
        for key in ('SWAYSOCK','DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
            if key in native:os.environ[key]=native[key]
        qa.wait(lambda:qa.control('status'));os.environ['QT_QPA_PLATFORM']='offscreen';app=QApplication.instance() or QApplication([])
        qa.control('tray');time.sleep(.5);qa.control('tray')
        def wait(check,timeout=10):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                app.processEvents();value=check()
                if value:return value
                time.sleep(.04)
            raise AssertionError(qa.control('status'))
        fixture=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tools/qa-xembed-fixture.py')],env=native,stdout=fixture_log,stderr=log)
        status=wait(lambda:(s if (s:=qa.control('status'))['tray'] else None));print('REGISTERED',status['tray'],flush=True)
        qa.control('tray');time.sleep(.6)
        subprocess.run(['grim','/tmp/orbit-legacy-proxy-panel.png'],env=native,check=True,timeout=5,stdout=log,stderr=log)
        qa.control('tray');time.sleep(.3)
        pointer=inputs.VirtualPointer(native);pointer.move(100,100)
        qa.control('qa-tray-activate-first')
        if '--activation' in sys.argv:wait(lambda:'CLICK' in Path('/tmp/orbit-xembed-fixture.log').read_text(),8)
        fixture.terminate();fixture.wait(timeout=3);wait(lambda:not qa.control('status')['tray'])
        assert not qa.control('status')['qml_errors'];pointer.close();pointer=None
        qa.control('quit');session.wait(timeout=15)
        print(json.dumps(dict(private_headless_only=True,xembed_registration=True,orbit_activation_roundtrip=(True if '--activation' in sys.argv else 'unverified: upstream GTK XTest delivery'),exit_cleanup=True,qml_errors=[])),flush=True)
    finally:
        if pointer:pointer.close()
        if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
        if session and session.poll() is None and native:
            try:command('exit')
            except Exception:pass
        if session and session.poll() is None:session.terminate();session.wait(timeout=5)

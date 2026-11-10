"""Exercise new essentials with private input/output and an unreachable audio server."""
import importlib.util,json,os,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
qa=load('essential_qa','qa-screenshots-wayland.py');inputs=load('essential_input','qa_wayland_input.py')
from sway_events import request,command
session=pointer=native=None
with tempfile.TemporaryDirectory(prefix='orbit-essentials-') as temp,open('/tmp/orbit-essentials-qa.log','w') as log:
    settings=Path(temp)/'settings.json';settings.write_text(json.dumps({'profile':'economy','darkLevel':'black','compact':True,'reducedMotion':True,'desktopIcons':False}))
    env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temp+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=temp+'/config',PULSE_SERVER='unix:'+temp+'/no-audio-server')
    try:
        session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        _,native=qa.wait(lambda:qa.native_process(settings),30);assert native['ORBIT_NESTED']=='1'
        for k in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
            if k in native:os.environ[k]=native[k]
        status=lambda:qa.control('status')
        qa.wait(status);pointer=inputs.VirtualPointer(native)
        def item(name):return qa.wait(lambda:qa.control('qa-shell-item:'+name),5)
        def click(name):
            r=item(name);assert r['visible'] and r['enabled'],(name,r);s=status()['screen_geometry']
            pointer.click(round(r['x']+r['width']/2),round(r['y']+r['height']/2),width=s['width'],height=s['height'])
        def tab(index):
            r=item('systemSettingsTabs');s=status()['screen_geometry']
            pointer.click(round(r['x']+r['width']*(index+.5)/3),round(r['y']+r['height']/2),width=s['width'],height=s['height'])
            qa.wait(lambda:item('systemSettingsPanel').get('section')==index,4)
        # Actual hardware-key binding, without a path to the real audio server.
        stamp=int(time.monotonic()*1000)&0xffffffff
        pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,115,1));pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,115,0));pointer.roundtrip()
        qa.wait(lambda:status().get('notice')=='No audio output is available',4)
        print('PASS compositor hardware key reaches existing controls safely',flush=True)
        command('output HEADLESS-1 mode 1600x1000');qa.wait(lambda:status()['screen_geometry']['width']==1600,5)
        time.sleep(.5)
        qa.control('quick');time.sleep(.3)
        print('LINK',item('systemSettingsLink'),flush=True)
        subprocess.run(['grim','/tmp/orbit-essentials-quick.png'],env=native,check=True,timeout=5,stdout=log,stderr=log)
        click('systemSettingsLink')
        try:qa.wait(lambda:status()['panel']=='system-settings',5)
        except AssertionError:print('SYSTEM LINK FAILED',status(),flush=True);raise
        click('naturalScrollToggle');qa.wait(lambda:status()['input_settings']['naturalScroll'],5)
        saved=(Path(temp)/'data/input.conf').read_text();assert 'natural_scroll enabled' in saved and 'xkb_layout' not in saved,saved
        print('PASS explicit input control persists without resetting keyboard',flush=True)
        tab(1);click('idleLockToggle');qa.wait(lambda:json.loads(settings.read_text()).get('idleLockEnabled') is False,4)
        assert not status()['idle_policy']['running'];print('PASS private lock policy preferences persist without starting a locker',flush=True)
        tab(2)
        try:qa.wait(lambda:status()['display_settings'].get('available'),5)
        except AssertionError:print('DISPLAY FAILED',status()['display_settings'],request(3),flush=True);raise
        def scale(index):
            click('displayScalePickerToggle');click('displayScalePickerChoice'+str(index));click('displayApply')
            qa.wait(lambda:status()['display_settings'].get('pending'),5)
        scale(1) # 75%, increasing logical space in this disposable headless output.
        click('displayApply');qa.wait(lambda:not status()['display_settings'].get('pending') and not status()['display_settings'].get('busy'),5)
        assert 'scale 0.75' in (Path(temp)/'data/outputs.conf').read_text()
        print('PASS actual display Apply/Keep persists confirmed settings',flush=True)
        scale(2);click('displayRevert');qa.wait(lambda:not status()['display_settings'].get('pending') and not status()['display_settings'].get('busy'),5)
        qa.wait(lambda:abs(request(3)[0]['scale']-.75)<.01,5)
        print('PASS explicit Revert restores previous confirmed scale',flush=True)
        scale(2);qa.wait(lambda:not status()['display_settings'].get('pending') and not status()['display_settings'].get('busy'),22)
        qa.wait(lambda:abs(request(3)[0]['scale']-.75)<.01,5)
        assert 'scale 0.75' in (Path(temp)/'data/outputs.conf').read_text()
        assert not status()['qml_errors'],status()['qml_errors']
        print('PASS unattended display timeout restores prior mode without overwriting config',flush=True)
        subprocess.run(['grim','/tmp/orbit-essentials-displays.png'],env=native,check=True,timeout=5,stdout=log,stderr=log)
        if '--measure' in sys.argv:
            qa.control('system-settings');time.sleep(.3)
            command('output HEADLESS-1 mode 1280x720 scale 1');qa.wait(lambda:status()['screen_geometry']['width']==1280,5);time.sleep(.5)
            metrics=load('essential_metrics','qa-process-metrics.py').idle_sample(native)
            metrics['scope']='Warm private 1280x720 Economy/Black/compact desktop after Input/Lock/Displays and larger-output display Keep/Revert/timeout. Includes compositor, bus, shell, Rust and helpers. Audio server intentionally unreachable; desktop icons off. Development measurement; not certification on physical 4GB hardware.'
            (ROOT/'essentials-metrics.json').write_text(json.dumps(metrics,indent=2)+'\n');print('METRICS',json.dumps(metrics),flush=True)
        pointer.close();pointer=None;qa.control('quit');session.wait(timeout=15)
        print(json.dumps({'private_headless_only':True,'checks':6,'qml_errors':[]}),flush=True)
    finally:
        if pointer:pointer.close()
        if session and session.poll() is None and native:
            try:command('exit')
            except Exception:pass
        if session and session.poll() is None:session.terminate();session.wait(timeout=5)

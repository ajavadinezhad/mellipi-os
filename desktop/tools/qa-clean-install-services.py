#!/usr/bin/env python3
"""Owned disposable-VM service checks; never run on a normal desktop/host."""
import argparse,json,os,pwd,secrets,subprocess,sys,time
from pathlib import Path
ROOT=Path('/usr/lib/abstract');SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT

def guest():
    if Path('/etc/hostname').read_text().strip()!='abstract-qa' or not Path('/var/lib/cloud/instance').exists() or not Path('/home/abstract/qa-guest.py').is_file() or pwd.getpwuid(os.getuid()).pw_name!='abstract':
        raise RuntimeError('This helper requires the owned Mellipi QA VM desktop user')
    sys.path.insert(0,str(SOURCE_ROOT))

def command(args,allow_failure=False):
    result=subprocess.run(args,capture_output=True,text=True,timeout=12)
    if result.returncode and not allow_failure:raise RuntimeError(Path(args[0]).name+' failed: '+result.stderr.strip()[:200])
    return result

def session_environment():
    sessions=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            if entry.stat().st_uid!=os.getuid():continue
            args=(entry/'cmdline').read_bytes().split(b'\0')
            if str(SOURCE_ROOT/'native_app.py').encode() not in args:continue
            env=dict(pair.split(b'=',1) for pair in (entry/'environ').read_bytes().split(b'\0') if b'=' in pair)
            if env.get(b'ORBIT_NATIVE_CONTROL') and not env.get(b'ORBIT_NESTED'):sessions.append(env)
        except OSError:continue
    if len(sessions)!=1:raise RuntimeError('Expected one owned real VM native desktop; no guest action performed')
    for name in ('XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','WAYLAND_DISPLAY','XDG_SESSION_ID','ORBIT_NATIVE_CONTROL'):
        if name.encode() in sessions[0]:os.environ[name]=sessions[0][name.encode()].decode()
    os.environ['ORBIT_QT']='5'
    return os.environ.copy()

def status():
    guest();apt=command(['pgrep','-x','apt-get'],True)
    if apt.returncode==0:return dict(apt_running=True,vm_only=True)
    result=dict(apt_running=False,vm_only=True)
    try:env=session_environment();result['native_session_ready']=True
    except RuntimeError:env=None;result['native_session_ready']=False
    network=command(['nmcli','-t','-f','STATE,CONNECTIVITY,WIFI','general'],True)
    devices=command(['nmcli','-t','-f','TYPE,STATE','device'],True)
    saved=command(['nmcli','-t','-f','TYPE','connection','show'],True)
    result['network']=dict(daemon_available=network.returncode==0,general=network.stdout.strip()[:160],device_types_and_states=devices.stdout.splitlines()[:16],saved_connection_count=len(saved.stdout.splitlines()) if saved.returncode==0 else None,saved_connections_available=saved.returncode==0,unmanaged_devices_present=any(row.endswith(':unmanaged') for row in devices.stdout.splitlines()))
    if env:
        from session.xdg_autostart import running_executables,POLKIT_EXECUTABLES
        agents=running_executables(environment=env,names=POLKIT_EXECUTABLES)
        result['polkit']=dict(same_login_agent_present=bool(agents),agent_names=sorted(agents))
        audio=command(['pactl','-f','json','info'],True)
        result['audio']=dict(server_available=audio.returncode==0)
        if audio.returncode==0:
            info=json.loads(audio.stdout);result['audio'].update(server_name=info.get('server_name',''),sink_count=len(json.loads(command(['pactl','-f','json','list','sinks']).stdout)),source_count=len(json.loads(command(['pactl','-f','json','list','sources']).stdout)))
    return result

def audio_fixture():
    guest();session_environment();os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
    from qt_compat import QApplication
    from system_services import SystemServices,audio_snapshot
    app=QApplication([]);app.setApplicationName('abstract-owned-vm-audio-qa')
    # Device selection normally moves application streams. Never disturb any
    # preexisting guest capture/playback while this acceptance fixture runs.
    for kind in ('sink-inputs','source-outputs'):
        if json.loads(command(['pactl','-f','json','list',kind]).stdout):raise RuntimeError('Guest has active audio streams; fixture deferred')
    original=json.loads(command(['pactl','-f','json','info']).stdout)
    sink='abstract_qa_'+secrets.token_hex(4);source=sink+'_mic';modules=[];service=None;notices=[];checks={}
    def rows(kind):return json.loads(command(['pactl','-f','json','list',kind]).stdout)
    def device(kind,name):return next(row for row in rows(kind) if row['name']==name)
    def percent(row):return round(sum(int(channel['value_percent'].rstrip('%')) for channel in row['volume'].values())/len(row['volume']))
    def wait(condition,seconds=15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents()
            if condition():return
            time.sleep(.02)
        raise RuntimeError('Owned VM audio fixture timed out')
    def invoke(fn):
        fn();wait(lambda:not service.pending)
        if notices:raise RuntimeError('Audio operation failed: '+notices[-1][:180])
    try:
        module=command(['pactl','load-module','module-null-sink','sink_name='+sink,'sink_properties=device.description=Abstract_QA_virtual_output']).stdout.strip()
        if not module.isdigit():raise RuntimeError('Invalid owned output module id')
        modules.append(module)
        module=command(['pactl','load-module','module-remap-source','master='+sink+'.monitor','source_name='+source,'source_properties=device.description=Abstract_QA_virtual_microphone']).stdout.strip()
        if not module.isdigit():raise RuntimeError('Invalid owned input module id')
        modules.append(module)
        wait(lambda:any(row['name']==source for row in rows('sources')))
        service=SystemServices(enabled=False);service.notice.connect(notices.append)
        invoke(lambda:service.setOutputDevice(sink));invoke(lambda:service.setVolume(37))
        if percent(device('sinks',sink))!=37:raise RuntimeError('Output volume readback mismatch')
        checks['output_select_and_volume']=True
        invoke(service.toggleMute)
        if not device('sinks',sink)['mute']:raise RuntimeError('Output mute readback mismatch')
        invoke(service.toggleMute)
        if device('sinks',sink)['mute']:raise RuntimeError('Output unmute readback mismatch')
        checks['output_mute_unmute']=True
        invoke(lambda:service.setInputDevice(source));invoke(lambda:service.setInputVolume(43))
        if percent(device('sources',source))!=43:raise RuntimeError('Input volume readback mismatch')
        checks['input_select_and_level']=True
        invoke(service.toggleInputMute)
        if not device('sources',source)['mute']:raise RuntimeError('Input mute readback mismatch')
        invoke(service.toggleInputMute)
        if device('sources',source)['mute']:raise RuntimeError('Input unmute readback mismatch')
        checks['input_mute_unmute']=True
        snapshot=audio_snapshot()
        if snapshot['defaultOutput']!=sink or snapshot['defaultInput']!=source or not snapshot['inputAvailable']:raise RuntimeError('Default route snapshot mismatch')
        checks['actual_audio_backend_snapshot']=True
    finally:
        if service:service.close()
        cleanup=[]
        for kind,key in (('sink','default_sink_name'),('source','default_source_name')):
            previous=original.get(key)
            if previous and any(row['name']==previous for row in rows(kind+'s')):
                cleanup.append(command(['pactl','set-default-'+kind,previous],True).returncode==0)
        for module in reversed(modules):cleanup.append(command(['pactl','unload-module',module],True).returncode==0)
        if modules:
            wait(lambda:not any(row['name'] in (sink,source,sink+'.monitor') for kind in ('sinks','sources') for row in rows(kind)))
            checks['owned_modules_removed']=True
            # PipeWire's automatic fallback sink may disappear when the fixture
            # is created, then return after the last null module is unloaded.
            for kind,key in (('sink','default_sink_name'),('source','default_source_name')):
                previous=original.get(key)
                if previous:
                    wait(lambda:any(row['name']==previous for row in rows(kind+'s')))
                    cleanup.append(command(['pactl','set-default-'+kind,previous],True).returncode==0)
            restored=json.loads(command(['pactl','-f','json','info']).stdout)
            checks['original_defaults_restored']=all(not original.get(key) or restored.get(key)==original[key] for key in ('default_sink_name','default_source_name'))
            if not all(cleanup) or not checks['original_defaults_restored']:raise RuntimeError('Owned VM audio fixture cleanup failed')
    return dict(vm_only=True,virtual_devices_only=True,hardware_audio_validated=False,checks=checks)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('status','audio'));args=parser.parse_args()
    print(json.dumps(status() if args.action=='status' else audio_fixture()))
if __name__=='__main__':main()

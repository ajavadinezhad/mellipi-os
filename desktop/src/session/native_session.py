#!/usr/bin/env python3
"""Standalone native session owner. Never replaces a running graphical session."""
import argparse,json,os,selectors,signal,socket,sqlite3,subprocess,sys,threading,time,shutil,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
from session.child_events import ChildEvents,reap_children
BINARY=ROOT/'.native-runtime/bin/orbit-compositor'
LIB=ROOT/'.native-drm-runtime/usr/lib/x86_64-linux-gnu'

class BoundedLog:
    """One bounded current log and one backup; only parent threads write files."""
    def __init__(self,path,limit=1024*1024):
        self.path=Path(path);self.limit=limit;self.lock=threading.RLock();self.handle=None
        self._open()
    def _open(self):
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
        os.fchmod(fd,0o600);self.handle=os.fdopen(fd,'ab',buffering=0)
        if os.fstat(fd).st_size>self.limit:self._rotate()
    def _rotate(self):
        self.handle.close()
        # Replace the backup itself, never follow a backup symlink.
        os.replace(self.path,self.path.with_suffix(self.path.suffix+'.1'))
        self._open()
        # Old versions may have left an oversized file. Retain only its tail.
        backup=self.path.with_suffix(self.path.suffix+'.1')
        fd=os.open(backup,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW)
        with os.fdopen(fd,'r+b',buffering=0) as previous:
            if os.fstat(fd).st_size>self.limit:
                previous.seek(-self.limit,os.SEEK_END);tail=previous.read(self.limit)
                previous.seek(0);previous.write(tail);previous.truncate()
    def write(self,data):
        with self.lock:
            data=data[-self.limit:]
            if os.fstat(self.handle.fileno()).st_size+len(data)>self.limit:self._rotate()
            self.handle.write(data)
    def flush(self):pass # unbuffered
    def __enter__(self):return self
    def __exit__(self,*_):
        with self.lock:self.handle.close()

def drain_log(fd,log):
    try:
        with os.fdopen(fd,'rb',buffering=0) as source:
            while True:
                chunk=source.read(65536)
                if not chunk:return
                log.write(chunk)
    except (OSError,ValueError):pass # owner shutdown may close the bounded sink

def compositor_environment(environment=None):
    env=dict(os.environ if environment is None else environment)
    env['LD_LIBRARY_PATH']=str(LIB)+((':'+env['LD_LIBRARY_PATH']) if env.get('LD_LIBRARY_PATH') else '')
    env.setdefault('ORBIT_NATIVE_PROFILE','economy')
    return env

def graphical_session(environment):
    return any(environment.get(key) for key in ('WAYLAND_DISPLAY','DISPLAY','SWAYSOCK'))

def request(path,command,timeout=1):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(timeout);connection.connect(str(path));connection.sendall((json.dumps({'command':command})+'\n').encode())
        buffer=b''
        while b'\n' not in buffer:
            part=connection.recv(65536)
            if not part:raise OSError('native compositor disconnected')
            buffer+=part
            if len(buffer)>1024*1024:raise OSError('oversized compositor response')
        return json.loads(buffer.split(b'\n',1)[0])

def check(environment=None,login=False):
    env=compositor_environment(environment);issues=[]
    if not BINARY.is_file() or not os.access(BINARY,os.X_OK):issues.append('Build the native backend: ./tools/build-native-compositor.sh --features drm')
    if not (ROOT/'backend/target/release/orbit-core').is_file():issues.append('Build the shell core: ./tools/build-core.sh')
    try:
        result=subprocess.run(['/usr/bin/python3','-c','from PyQt5 import QtCore,QtQuick,QtWidgets; from pathlib import Path; import gi,ctypes; ctypes.CDLL("libLayerShellQtInterface.so.5"); plugin=Path(QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.PluginsPath))/"wayland-shell-integration/liblayer-shell.so"; loader=QtCore.QPluginLoader(str(plugin)); assert loader.load(), loader.errorString()'],capture_output=True,timeout=8,env=env)
        if result.returncode:issues.append('Qt5/PyQt5 or the Wayland layer-shell plugin is unavailable. Install qtwayland5, layer-shell-qt and liblayershellqtinterface5 for this Qt version.')
    except (OSError,subprocess.TimeoutExpired):issues.append('System Qt5 readiness check failed.')
    preflight=None
    if BINARY.is_file():
        try:
            result=subprocess.run([str(BINARY),'--drm-preflight'],capture_output=True,text=True,timeout=8,env=env)
            preflight=json.loads(result.stdout.strip().splitlines()[-1])
            if not preflight.get('compiled'):issues.append('Native binary lacks DRM support; rebuild with --features drm.')
            elif not preflight.get('cards'):issues.append('No /dev/dri/card* device detected; native login needs a DRM/KMS GPU.')
        except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):issues.append('Native preflight failed; rebuild after ./tools/prepare-native-drm.py.')
    from session.preflight import inspect
    prerequisites=inspect(env,phase='login' if login else 'install')
    issues.extend(prerequisites['issues'])
    return {'ok':not issues,'issues':issues,'warnings':prerequisites['warnings'],'prerequisites':prerequisites,'readiness_scope':'login' if login else 'installation','preflight':preflight,'hardware_validated':False,'changes_active_session':False,'login_entry':'Mellipi' if env.get('ORBIT_INSTALLED_SESSION')=='1' else 'Mellipi (Experimental)','current_graphical_session':graphical_session(env)}

def wait_ready(process,log,timeout=20):
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ);buffer=b'';deadline=time.monotonic()+timeout
    try:
        while time.monotonic()<deadline:
            for key,_ in selector.select(min(.25,max(0,deadline-time.monotonic()))):
                chunk=os.read(key.fd,65536)
                if not chunk:raise OSError('Native compositor exited before readiness; inspect data/native-session.log')
                buffer+=chunk
                if len(buffer)>256*1024:raise OSError('Oversized native readiness stream')
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1);log.write(line+b'\n');log.flush()
                    try:value=json.loads(line)
                    except (ValueError,UnicodeError):continue
                    if isinstance(value,dict) and value.get('ready') and value.get('wayland_display') and value.get('control'):
                        if buffer:log.write(buffer);log.flush()
                        return value
            if process.poll() is not None:raise OSError('Native compositor exited before readiness')
        raise TimeoutError('Native compositor did not become ready within 20 seconds')
    finally:selector.close()

def session_environment(ready,environment=None,nested=False):
    env=dict(os.environ if environment is None else environment)
    # SWAYSOCK must never point to the outer session or masquerade as native IPC.
    env.pop('SWAYSOCK',None);env.pop('DISPLAY',None)
    env.update(WAYLAND_DISPLAY=str(ready['wayland_display']),ORBIT_NATIVE_CONTROL=str(ready['control']),
               XDG_CURRENT_DESKTOP='Orbit',XDG_SESSION_DESKTOP='orbit-native',XDG_SESSION_TYPE='wayland')
    # Portal activation happens in the owner before the shell sources its Qt
    # environment. Publish native portal selection at that same boundary.
    configs=str(SOURCE_ROOT/'session/configs')
    dirs=env.get('XDG_CONFIG_DIRS','/etc/xdg').split(':')
    env['XDG_CONFIG_DIRS']=':'.join([configs,*[value for value in dirs if value and value!=configs]])
    env['ORBIT_NATIVE_PROFILE']='economy'
    if nested:env['ORBIT_NESTED']='1'
    else:
        env.pop('ORBIT_NESTED',None)
        env.pop('XDG_DESKTOP_PORTAL_DIR',None)
    return env

def transfer_previous_state(environment,nested=False):
    # Run only after a real installed compositor is ready, before its shell.
    # Checks, previews and failed/existing-session starts cannot consume state.
    if nested or environment.get('ORBIT_INSTALLED_SESSION')!='1':return
    try:
        from state_handoff import consume
        result=consume(environment)
        if result['copied']:print('Mellipi: previous desktop state transferred',flush=True)
        if result['preserved']:print('Mellipi: destination edits preserved during state handoff',flush=True)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        print('Mellipi: previous state could not be fully transferred: '+str(error)[:180],file=sys.stderr,flush=True)

def stop_owned(process):
    if process is None or process.poll() is not None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=2)

def run(nested=False,no_shell=False,qa_seconds=None):
    if not nested and graphical_session(os.environ):raise RuntimeError('A graphical desktop is already running. Keep apps open; use --check or --nested here. Native DRM login starts only after deliberately logging out and choosing Mellipi.')
    if nested and not graphical_session(os.environ):raise RuntimeError('Nested preview needs an existing graphical session.')
    report=check(login=not nested)
    if not report['ok']:raise RuntimeError('\n'.join(report['issues']))
    log_path=Path(os.environ.get('ORBIT_DATA',str(ROOT/'data')))/'native-session.log';log_path.parent.mkdir(parents=True,exist_ok=True)
    stopping=threading.Event();children=[];children_lock=threading.RLock();compositor=None;threads=[];previous={};events=ChildEvents()
    def stop(*_):stopping.set();events.wake()
    for signum in (signal.SIGTERM,signal.SIGINT):previous[signum]=signal.signal(signum,stop)
    with events,BoundedLog(log_path) as log:
        log_read,log_write=os.pipe()
        logger=threading.Thread(target=drain_log,args=(log_read,log),name='orbit-native-stderr',daemon=True)
        logger.start();threads.append(logger)
        try:
            compositor=subprocess.Popen([str(BINARY),*([] if nested else ['--drm'])],env=compositor_environment(),stdout=subprocess.PIPE,stderr=log_write,start_new_session=True)
            ready=wait_ready(compositor,log);environment=session_environment(ready,nested=nested)
            transfer_previous_state(environment,nested=nested)
            def drain():
                while True:
                    chunk=compositor.stdout.read(65536)
                    if not chunk:return
                    log.write(chunk)
            output=threading.Thread(target=drain,name='orbit-native-log',daemon=True);output.start();threads.append(output)
            # Xwayland is asynchronous; never reuse the outer desktop's DISPLAY.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and compositor.poll() is None:
                try:
                    status=request(ready['control'],'status')
                    if status.get('xdisplay') is not None:
                        environment['DISPLAY']=':'+str(status['xdisplay']);break
                    if status.get('xwayland_error'):break
                except (OSError,ValueError):pass
                stopping.wait(.05)
            print(json.dumps({'ready':True,'nested':nested,'wayland_display':ready['wayland_display'],'control':ready['control'],'display':environment.get('DISPLAY'),'hardware_validated':False}),flush=True)
            def launch(args,environment=None):
                with children_lock:
                    if stopping.is_set():return None
                    child=subprocess.Popen(args,env=environment,stderr=log_write,stdout=log_write,start_new_session=True);children.append(child);return child
            def release(child):
                with children_lock:
                    if child in children:children.remove(child)
            # Import services only after a ready compositor and dedicated env exist.
            from session import autostart
            def leave():
                try:request(ready['control'],'quit')
                except (OSError,ValueError):pass
                stop()
            if not no_shell:
                # Helpers read os.environ; the session owner has no private Qt paths.
                os.environ.update(environment)
                if not nested:
                    autostart.update_activation_environment()
                    from session.audiostart import start_enabled_audio
                    audio_start=start_enabled_audio(environment)
                    if not audio_start['ok']:print('Mellipi audio: '+audio_start['reason'],file=sys.stderr,flush=True)
                    from session import portal_service
                    portal=portal_service.backend_command(ROOT)
                    autostart.refresh_portals_at_login(environment,local_backend=bool(portal))
                    autostart.launch_optional_services(launch)
                    if portal:
                        from desktop import application_environment
                        worker=threading.Thread(target=portal_service.supervise,args=(portal,application_environment(),launch,release,stopping),name='abstract-portal',daemon=True)
                        worker.start();threads.append(worker)
                    autostart.launch_xdg_services(launch)
                watcher=threading.Thread(target=autostart.supervise_shell,args=(lambda:launch([str(ROOT/'run-native-shell.sh')],environment=environment),stopping,leave),kwargs={'release':release},name='orbit-native-shell',daemon=True)
                watcher.start();threads.append(watcher)
            # Wait on child exit/signals rather than waking the session owner
            # four times a second for its entire lifetime. QA has one timeout.
            def compositor_exited():
                compositor.wait();stop()
            monitor=threading.Thread(target=compositor_exited,name='orbit-native-exit',daemon=True)
            monitor.start();threads.append(monitor)
            deadline=None if qa_seconds is None else time.monotonic()+max(0,qa_seconds)
            while not stopping.is_set():
                reap_children(children,children_lock)
                remaining=None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining<=0:break
                events.wait(remaining)
            return compositor.returncode or 0
        finally:
            stop()
            # Only children started by this owner are terminated. No pkill, VT
            # change, display-manager action or signal to a pre-existing process.
            with children_lock:owned=list(children)
            for child in owned:stop_owned(child)
            stop_owned(compositor)
            os.close(log_write)
            for thread in threads:thread.join(timeout=1)
            for signum,handler in previous.items():signal.signal(signum,handler)

def main():
    parser=argparse.ArgumentParser(description=__doc__);checks=parser.add_mutually_exclusive_group();checks.add_argument('--check',action='store_true',help='Read-only installation checks; no active user login is required');checks.add_argument('--check-login',action='store_true',help='Read-only checks of this user login, bus and local seat');parser.add_argument('--nested',action='store_true');parser.add_argument('--no-shell',action='store_true');parser.add_argument('--qa-seconds',type=float);args=parser.parse_args()
    if args.check or args.check_login:
        report=check(login=args.check_login);print(json.dumps(report,indent=2));return 0 if report['ok'] else 1
    if args.qa_seconds is not None and (not args.nested or not args.no_shell or not 0<args.qa_seconds<=60):parser.error('--qa-seconds requires --nested --no-shell and a duration up to 60 seconds')
    if args.nested and not args.no_shell and not os.environ.get('ORBIT_NATIVE_NESTED_BUS'):
        bus=shutil.which('dbus-run-session')
        if not bus:print('Mellipi: dbus-run-session is required for a safely isolated nested shell',file=sys.stderr);return 1
        environment=dict(os.environ,ORBIT_NATIVE_NESTED_BUS='1')
        os.execvpe(bus,[bus,'--','/usr/bin/python3',str(Path(__file__).resolve()),*sys.argv[1:]],environment)
    try:
        if args.nested and not args.no_shell and not os.environ.get('ORBIT_DATA'):
            with tempfile.TemporaryDirectory(prefix='orbit-native-preview-') as data:
                os.environ['ORBIT_DATA']=data
                try:return run(args.nested,args.no_shell,args.qa_seconds)
                finally:os.environ.pop('ORBIT_DATA',None)
        return run(args.nested,args.no_shell,args.qa_seconds)
    except (OSError,RuntimeError,TimeoutError,ValueError) as error:print('Mellipi: '+str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

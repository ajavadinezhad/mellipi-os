#!/usr/bin/env python3
"""Launch an isolated nested Sway QA desktop; native login has its own owner."""
import argparse,json,os,re,select,shlex,shutil,signal,subprocess,tempfile
from pathlib import Path
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT

def session_config(environment=None):
    environment=os.environ if environment is None else environment
    config='\n'.join(line for line in (SOURCE_ROOT/'session/configs/sway-qa.conf').read_text().splitlines() if not re.match(r'bindsym Mod4\+[1-4] workspace',line))
    for key,page in [('Ctrl+Mod1+space','launcher'),('Ctrl+Mod1+s','quick'),('Ctrl+Mod1+q','quick')]:config+=f'\nbindsym {key} nop orbit-panel-{page}'
    for key,page in [('Mod1+Tab','switch-next'),('Mod1+Shift+Tab','switch-prev'),('--release Alt_L','switch-accept'),('--release Alt_R','switch-accept')]:config+=f'\nbindsym {key} nop orbit-{page}'
    config+='\nbindsym Print nop orbit-panel-screenshot'
    for key in ('Super_L','Super_R'):config+=f'\nbindsym --release {key} nop orbit-panel-launcher'
    for index in range(1,5):config+=f'\nbindsym Mod4+{index} nop orbit-workspace-{index}'
    from workspace_bindings import config_lines as workspace_shortcuts
    config+='\n'+'\n'.join(workspace_shortcuts())+'\n'
    config+='\noutput * bg #172329 solid_color\n'
    from hardware_bindings import config_lines
    config+='\n'+'\n'.join(config_lines())+'\n'
    from shortcut_config import config_lines as shortcuts
    config+='\n'+'\n'.join(shortcuts())+'\n'
    data=Path(environment.get('ORBIT_DATA',str(ROOT/'data')))
    for filename in ('outputs.conf','input.conf','shortcuts.conf'):
        settings=data/filename
        if not (environment.get('ORBIT_NESTED') and not environment.get('ORBIT_DATA')) and settings.is_file():config+='\ninclude '+shlex.quote(str(settings))+'\n'
    config+='\nexec /usr/bin/python3 '+shlex.quote(str(SOURCE_ROOT/'session/autostart.py'))+'\n'
    return config

def preflight():
    runtime=os.environ.get('ORBIT_WAYLAND_RUNTIME','system');missing=[]
    commands={name:shutil.which(name) for name in ('sway','Xwayland','dbus-run-session','swaybg','swayidle','swaylock','grim','slurp')}
    missing.extend(name for name,path in commands.items() if not path)
    for name in ('run-wayland-native.sh','session/autostart.py','session/configs/sway-qa.conf','native/Desktop.qml','backend/target/release/orbit-core'):
        if not ((SOURCE_ROOT if name.startswith('session/') else ROOT)/name).is_file():missing.append(name)
    if (ROOT/'backend/target/release/orbit-core').exists() and not os.access(ROOT/'backend/target/release/orbit-core',os.X_OK):missing.append('orbit-core executable permission')
    interpreter=Path('/usr/bin/python3') if runtime=='system' else ROOT/'.venv/bin/python'
    if not interpreter.is_file():missing.append(str(interpreter))
    if runtime=='system':
        check=subprocess.run([str(interpreter),'-c','from PyQt5 import QtCore,QtQuick,QtWidgets;import gi,ctypes;ctypes.CDLL("libLayerShellQtInterface.so.5")'],capture_output=True,text=True,check=False)
        if check.returncode:missing.append('system PyQt5/LayerShellQt/Gio runtime')
    else:
        for name in ('.wayland-runtime/usr/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.5','.wayland-runtime/usr/lib/python3/dist-packages/PyQt5/QtQuick.abi3.so'):
            if not (ROOT/name).exists():missing.append(name)
    return dict(ready=not missing,runtime=runtime,commands=commands,missing=missing,physical_lock_ready=Path('/etc/pam.d/swaylock').is_file(),session_entry=Path('/usr/share/wayland-sessions/orbit.desktop').is_file(),note='Readiness checks do not validate physical GPU/input, PAM authentication, suspend or screen sharing.')

LOG_LIMIT=1024*1024

def open_session_log():
    """One current capped log plus one previous run; user-only, no logger daemon."""
    path=ROOT/'data/wayland-session.log';path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise OSError('Refusing a symbolic link for the session log')
    if path.exists():
        previous=path.with_name(path.name+'.previous')
        if previous.is_symlink():raise OSError('Refusing a symbolic link for the previous session log')
        os.replace(path,previous);os.chmod(previous,0o600)
        if previous.stat().st_size>LOG_LIMIT:
            with previous.open('r+b') as handle:handle.truncate(LOG_LIMIT)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    return os.fdopen(descriptor,'wb',buffering=0)

def run_logged(command,env,log,limit=LOG_LIMIT):
    """Drain compositor output with a fixed disk budget and no periodic wakeup."""
    child=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    pidfd=None;handlers={};written=0
    try:
        pidfd=os.pidfd_open(child.pid,0);os.set_blocking(child.stdout.fileno(),False)
        def stop(signum,frame):
            if child.poll() is None:child.send_signal(signum)
        handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
        while True:
            ready,_,_=select.select([child.stdout,pidfd],[],[])
            if child.stdout in ready or pidfd in ready:
                eof=False
                while True:
                    try:data=os.read(child.stdout.fileno(),8192)
                    except BlockingIOError:break
                    if not data:eof=True;break
                    if written<limit:
                        chunk=data[:limit-written];log.write(chunk);written+=len(chunk)
                if eof or pidfd in ready:break
        code=child.wait();return 128-code if code<0 else code
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=4)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        for signum,handler in handlers.items():signal.signal(signum,handler)
        if pidfd is not None:os.close(pidfd)
        child.stdout.close()

def main():
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group();mode.add_argument('--nested',action='store_true');mode.add_argument('--headless',action='store_true');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.check:
        status=preflight();print(json.dumps(status,indent=2));return 0 if status['ready'] else 1
    if not (args.nested or args.headless):
        parser.error('The Orbit/Sway login session is retired. Use run-native-session.sh; Sway remains available only for isolated QA.')
    env=os.environ.copy()
    # A private Sway test must never inherit the physical native control socket.
    env.pop('ORBIT_NATIVE_CONTROL',None);env.pop('ORBIT_NATIVE_NESTED_BUS',None)
    env.update(XDG_CURRENT_DESKTOP='sway',XDG_SESSION_DESKTOP='orbit',XDG_SESSION_TYPE='wayland',QT_QPA_PLATFORM='wayland')
    if args.nested:env.update(ORBIT_NESTED='1',WLR_BACKENDS='x11',WLR_RENDERER='pixman',WLR_RENDERER_ALLOW_SOFTWARE='1',QT_QUICK_BACKEND='software')
    elif args.headless:env.update(ORBIT_NESTED='1',WLR_BACKENDS='headless',WLR_HEADLESS_OUTPUTS='1',WLR_RENDERER='pixman',QT_QUICK_BACKEND='software')
    else:
        # LightDM may inherit its X11 greeter display; physical login must not
        # accidentally nest Sway inside that display instead of opening DRM.
        for key in ('DISPLAY','WAYLAND_DISPLAY','SWAYSOCK'):env.pop(key,None)
    with tempfile.TemporaryDirectory(prefix='orbit-session-') as directory:
        path=Path(directory)/'config';path.write_text(session_config(env));command=['sway','--config',str(path)]
        try:
            if args.nested or args.headless:return subprocess.run(command,env=env).returncode
            with open_session_log() as log:return run_logged(command,env,log)
        except FileNotFoundError:
            print('Sway is unavailable. Install the distribution Sway QA dependencies; native login uses run-native-session.sh.',file=__import__('sys').stderr);return 1
        except KeyboardInterrupt:return 130

if __name__=='__main__':raise SystemExit(main())

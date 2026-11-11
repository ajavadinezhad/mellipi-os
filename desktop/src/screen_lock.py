"""One lightweight, shared locker launcher for idle, suspend and manual locking."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile,threading,socket,time
from pathlib import Path
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT

def locker_binary():
    local=ROOT/'.lock-runtime/bin/swaylock'
    return str(local) if local.is_file() and os.access(local,os.X_OK) else shutil.which('swaylock')

def command(environment=None,binary=None):
    env=os.environ if environment is None else environment
    identity=env.get('ORBIT_NATIVE_CONTROL') or env.get('SWAYSOCK')
    if not identity or not env.get('WAYLAND_DISPLAY'):raise ValueError('A Wayland Mellipi session is required')
    if env.get('ORBIT_NATIVE_CONTROL'):
        from native_compositor import NativeCompositor
        status=NativeCompositor(env['ORBIT_NATIVE_CONTROL']).status()
        if not status.get('capabilities',{}).get('secure_lock'):
            raise ValueError('Native session locking is not yet validated; use a supported Mellipi session for secure locking')
    runtime=Path(env.get('XDG_RUNTIME_DIR',''))
    if not runtime.is_absolute() or not runtime.is_dir():raise ValueError('The session runtime directory is unavailable')
    binary=binary or locker_binary();flock=shutil.which('flock')
    if not binary or not flock:raise ValueError('Install swaylock and util-linux before locking')
    directory=runtime/'orbit-locks'
    if directory.is_symlink():raise ValueError('Unsafe lock coordination directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.stat().st_uid!=os.getuid() or directory.stat().st_mode&0o077:raise ValueError('Lock coordination directory must be private to this user')
    ident=hashlib.sha256(identity.encode()).hexdigest()[:16];lock=directory/(ident+'.lock')
    if lock.is_symlink():raise ValueError('Unsafe lock coordination file')
    from lock_background import lock_style,cached_image,output_specs
    from preferences import Preferences
    style=lock_style(Preferences(env.get('ORBIT_SETTINGS_FILE')).values)
    # Metadata reads are bounded and optional: wallpaper can never delay/fail
    # secure lock merely because an output query or renderer is unavailable.
    rows=[]
    if env.get('ORBIT_NATIVE_CONTROL'):
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(.5);connection.connect(env['ORBIT_NATIVE_CONTROL']);connection.sendall(b'{"command":"snapshot"}\n');data=b''
                while not data.endswith(b'\n'):
                    block=connection.recv(16384)
                    if not block:break
                    data+=block
                    if len(data)>1048576:raise ValueError('Oversized output reply')
                value=json.loads(data)
                if isinstance(value,dict) and isinstance(value.get('outputs'),list):rows=value['outputs']
        except (OSError,ValueError,TypeError):pass
    images=[]
    try:
        specs=output_specs(rows) or [('',1280,720,1)]
        for name,width,height,scale in specs:
            image=cached_image(directory/'backgrounds',width,height,scale,style)
            images.append((name,image))
    except (OSError,ValueError,ImportError,AttributeError,RuntimeError) as error:
        print('Screen lock: themed wallpaper unavailable; secure lock remains enabled',file=sys.stderr)
        fallback=ROOT/'native/lock-background.png'
        if fallback.is_file():images=[('',fallback)]
    def color(key):return style[key].lstrip('#')
    args=[flock,'--nonblock','--no-fork','--conflict-exit-code','75',str(lock),binary,'--daemonize','--ignore-empty-password','--show-failed-attempts','--show-keyboard-layout','--indicator-caps-lock','--color',color('background'),
        '--indicator-idle-visible','--indicator-radius',str(round(58*min(1.2,style['textScale']))),'--indicator-thickness','3','--font','Sans','--font-size',str(round(16*style['textScale'])),
        '--inside-color',color('surface'),'--inside-clear-color',color('surface'),'--inside-ver-color',color('surface'),'--inside-wrong-color',color('surface'),'--inside-caps-lock-color',color('surface'),
        '--ring-color',color('accent'),'--ring-clear-color',color('accent'),'--ring-ver-color',color('warning'),'--ring-wrong-color',color('error'),'--ring-caps-lock-color',color('warning'),
        '--text-color',color('text'),'--text-clear-color',color('text'),'--text-ver-color',color('text'),'--text-wrong-color',color('text'),'--text-caps-lock-color',color('text'),
        '--key-hl-color',color('text'),'--bs-hl-color',color('warning'),'--line-color',color('border'),
        '--layout-bg-color',color('surface'),'--layout-border-color',color('border'),'--layout-text-color',color('text')]
    for name,image in images:args.extend(['--image',(name+':' if name else '')+str(image)])
    if images:args.extend(['--scaling','fit'])
    return args

def launch_and_wait(environment=None,timeout=8):
    """Launch off the GUI thread and report failure before daemon readiness.

    swaylock --daemonize exits its initial process only after the lock is ready.
    A regular temporary stderr file avoids waiting on a pipe inherited by the
    long-lived locker. This helper never tests credentials or kills a locker.
    """
    if environment is None:
        from desktop import application_environment
        environment=application_environment()
        for key in ('ORBIT_NATIVE_CONTROL','ORBIT_NESTED','ORBIT_SETTINGS_FILE'):
            if os.environ.get(key):environment[key]=os.environ[key]
    if environment.get('ORBIT_NESTED'):raise RuntimeError('Screen locking is disabled in nested preview sessions')
    timeout=max(.1,min(8,float(timeout)))
    with tempfile.TemporaryFile() as errors:
        try:
            process=subprocess.Popen(['/usr/bin/python3',str(SOURCE_ROOT/'screen_lock.py')],env=environment,start_new_session=True,stdout=subprocess.DEVNULL,stderr=errors)
        except OSError as error:raise RuntimeError('Screen lock could not start: '+str(error)) from error
        try:code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            # The compositor may already be locked or waiting for its first
            # configure. Never terminate it merely to satisfy a UI deadline.
            def reap():
                try:process.wait()
                except OSError:pass
            threading.Thread(target=reap,name='orbit-lock-reaper',daemon=True).start()
            raise RuntimeError('Screen lock startup did not confirm readiness. It may still appear; do not assume the session is locked.') from error
        control=environment.get('ORBIT_NATIVE_CONTROL')
        if control and code in (0,75):
            from native_compositor import NativeCompositor
            compositor=NativeCompositor(control)
            deadline=time.monotonic()+timeout
            while True:
                if compositor.status().get('locked'):
                    return
                if code==0 or time.monotonic()>=deadline:
                    raise RuntimeError('The compositor did not confirm the screen lock')
                time.sleep(.1)
        if code:
            errors.seek(0);details=' '.join(errors.read(1024).decode('utf-8','replace').split())[:240]
            raise RuntimeError('Screen lock failed'+(f': {details}' if details else f' (exit {code})'))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--allow-nested-test',action='store_true');args=parser.parse_args()
    try:
        binary=locker_binary()
        if args.check:
            if not binary:raise ValueError('swaylock is unavailable')
            version=subprocess.run([binary,'--version'],capture_output=True,text=True,timeout=3,check=True)
            print(json.dumps(dict(binary=binary,version=(version.stdout+version.stderr).strip(),pam_config=Path('/etc/pam.d/swaylock').is_file())));return 0
        if os.environ.get('ORBIT_NESTED') and not args.allow_nested_test:raise ValueError('Locking is disabled in nested preview sessions')
        if not Path('/etc/pam.d/swaylock').is_file():raise ValueError('The system swaylock PAM configuration is missing')
        args=command(binary=binary)
        from desktop import application_environment
        environment=application_environment()
        environment['ORBIT_LOCK_TEXTBOX']='1'
        from preferences import Preferences
        environment['ORBIT_LOCK_CLOCK_24']='1' if Preferences(os.environ.get('ORBIT_SETTINGS_FILE')).values['clock24'] else '0'
        if os.environ.get('ORBIT_NATIVE_CONTROL'):environment['ORBIT_NATIVE_CONTROL']=os.environ['ORBIT_NATIVE_CONTROL']
        if os.environ.get('ORBIT_NESTED'):environment['ORBIT_LOCK_QA']='1'
        os.execvpe(args[0],args,environment)
    except (OSError,ValueError,subprocess.SubprocessError) as error:print('Screen lock: '+str(error),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Session services and bounded, event-driven shell recovery."""
import os,signal,subprocess,sys,threading,socket,shutil,time,shlex
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
from sway_events import request,receive,HEADER,MAGIC

# Initial launch plus at most three retries. A repeated crash never spins forever.
RESTART_DELAYS=(.5,1.0,2.0)

def supervise_shell(start,stopping,exit_session,delays=RESTART_DELAYS,release=None):
    """Wait for each shell, restart crashes, and leave compositor on explicit clean exit.

    Dependencies are passed in so recovery can be tested without a compositor or
    real child processes. Event.wait provides interruptible backoff, not polling.
    """
    attempt=0
    while True:
        if stopping.is_set():return
        began=time.monotonic()
        try:
            process=start()
            if process is None:return
            code=process.wait()
            if release:release(process)
        except OSError as error:
            print('Mellipi shell could not start: '+str(error),file=sys.stderr,flush=True)
            code=1
        if stopping.is_set():return
        if code==0:exit_session();return
        if time.monotonic()-began>=60:attempt=0
        if attempt==len(delays):
            print('Mellipi shell recovery exhausted; preserving compositor and open applications',file=sys.stderr,flush=True)
            return
        print(f'Mellipi shell exited ({code}); restarting {attempt+1}/{len(delays)}',file=sys.stderr,flush=True)
        if stopping.wait(delays[attempt]):return
        attempt+=1

# Only session-routing/toolkit discovery variables are imported. Provider secrets
# and arbitrary process environment never enter D-Bus/systemd activation state.
ACTIVATION_VARIABLES=('WAYLAND_DISPLAY','DISPLAY','SWAYSOCK','XDG_CURRENT_DESKTOP','XDG_SESSION_DESKTOP','XDG_SESSION_TYPE','XDG_DATA_DIRS','XDG_CONFIG_DIRS','XDG_DESKTOP_PORTAL_DIR')

def activation_arguments(environment=None):
    environment=os.environ if environment is None else environment
    command=['dbus-update-activation-environment']
    if not environment.get('ORBIT_NESTED'):command.append('--systemd')
    return command+[key for key in ACTIVATION_VARIABLES if key in environment]

def update_activation_environment():
    try:
        result=subprocess.run(activation_arguments(),check=False,timeout=5)
        if result.returncode:
            print('Orbit: activation environment was not fully updated',file=sys.stderr,flush=True)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired) as error:
        print('Orbit: activation environment unavailable: '+str(error),file=sys.stderr,flush=True)
        return False

def refresh_portals_at_login(environment=None,local_backend=False):
    """Retire old Wayland routing only at a new real login, never shell recovery.

    Modern D-Bus portal services activate through the user systemd manager. Clear
    the old test override there, and refresh only already-running portal units.
    New/unused providers remain demand-started. Non-systemd sessions use their
    fresh login bus and normal activation instead.
    """
    env=os.environ if environment is None else environment
    if env.get('ORBIT_NESTED') or not shutil.which('systemctl'):return False
    try:
        subprocess.run(['systemctl','--user','unset-environment','XDG_DESKTOP_PORTAL_DIR'],env=env,timeout=5,check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if local_backend:
            # The native owner supplies the small compatibility backend. Retire
            # stale providers only here, after the previous login has ended.
            result=subprocess.run(['systemctl','--user','stop','xdg-desktop-portal.service','xdg-desktop-portal-wlr.service'],env=env,timeout=8,check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:
            result=subprocess.run(['systemctl','--user','try-restart','xdg-desktop-portal-wlr.service','xdg-desktop-portal-gtk.service','xdg-desktop-portal.service'],env=env,timeout=8,check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False

def optional_service_commands(environment=None):
    environment=os.environ if environment is None else environment
    if environment.get('ORBIT_NESTED'):return []
    commands=[]
    from session.assistive import permission_agent,configured_input_method
    for command in (permission_agent(),configured_input_method(environment)):
        if command:commands.append(command)
    # The native shell's IdlePolicy owns the single configurable swayidle child.
    # Starting another timer here would retain the old ten-minute policy.
    return commands

def launch_optional_services(launch):
    # A display manager or another login helper may already own the agent.
    from session.xdg_autostart import running_executables,POLKIT_EXECUTABLES
    environment=os.environ
    existing=running_executables()
    polkit_running=bool(running_executables(environment=environment,names=POLKIT_EXECUTABLES))
    for command in optional_service_commands():
        if not command:continue
        name=Path(command[0]).name
        if name in POLKIT_EXECUTABLES:
            if polkit_running:continue
        elif name in existing:continue
        try:
            from desktop import application_environment
            from session.assistive import service_environment
            launch(command,environment=service_environment(command,application_environment()))
            if name in POLKIT_EXECUTABLES:polkit_running=True
        except OSError as error:
            print('Orbit: optional session service unavailable: '+str(error),file=sys.stderr,flush=True)

def launch_xdg_services(launch):
    # Called once by the session owner, never by the recoverable shell thread.
    if os.environ.get('ORBIT_NESTED'):return []
    from desktop import application_environment
    from session.xdg_autostart import launch_autostart
    return launch_autostart(launch,application_environment(),reserved_commands=optional_service_commands())

def main():
    if not os.environ.get('ORBIT_NESTED'):
        print('The old Orbit/Sway login session is retired; use the native session.',file=sys.stderr);return 1
    children=[];lock=threading.RLock();stopping=threading.Event();leaving=threading.Event();sock=None;watcher=None
    wake_read,wake_write=os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
    def terminate(process,signum=signal.SIGTERM):
        # Each session service has its own group, including the shell supervisor,
        # native UI and Rust child. Never signal the user's outer desktop group.
        try:os.killpg(process.pid,signum)
        except ProcessLookupError:pass
    def stop(*_):
        stopping.set()
        try:os.write(wake_write,b'x')
        except OSError:pass
        with lock:
            for process in children:terminate(process)
    def launch(args,environment=None):
        with lock:
            if stopping.is_set():return None
            process=subprocess.Popen(args,env=environment,start_new_session=True);children.append(process);return process
    def release(process):
        # Retire each finished supervisor immediately, including any stranded
        # descendants, so long sessions never retain stale process-group IDs.
        with lock:
            terminate(process)
            if process in children:children.remove(process)
    def exit_session():
        leaving.set()
        try:request(0,'exit')
        except (OSError,ConnectionError):pass
    previous={signum:signal.signal(signum,stop) for signum in (signal.SIGTERM,signal.SIGINT)}
    try:
        update_activation_environment()
        # Subscribe before launching the shell: even an immediate clean shell exit
        # must be observed, rather than leaving this process waiting indefinitely.
        sock=socket.socket(socket.AF_UNIX);sock.settimeout(3);sock.connect(os.environ['SWAYSOCK']);data=b'["shutdown"]';sock.sendall(HEADER.pack(MAGIC,len(data),2)+data);receive(sock);sock.settimeout(None)
        launch_optional_services(launch)
        launch_xdg_services(launch)
        watcher=threading.Thread(target=supervise_shell,args=(lambda:launch([str(ROOT/'run-wayland-native.sh')]),stopping,exit_session),kwargs={'release':release},name='orbit-session-shell',daemon=True);watcher.start()
        import select
        while not stopping.is_set():
            ready,_,_=select.select([sock,wake_read],[],[])
            if wake_read in ready:break
            if sock in ready:
                _,event=receive(sock)
                if event.get('change')=='exit':break
    except (OSError,ConnectionError) as error:
        if not stopping.is_set() and not leaving.is_set():print('Mellipi session ended: '+str(error),file=sys.stderr,flush=True)
    finally:
        stop()
        # Requesting exit is harmless if Sway already disconnected; explicit
        # autostart termination must not leave a compositor without its shell.
        exit_session()
        with lock:processes=list(children)
        for process in processes:
            try:process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                terminate(process,signal.SIGKILL);process.wait()
        if watcher:watcher.join(timeout=2)
        if sock:sock.close()
        for signum,handler in previous.items():signal.signal(signum,handler)
        os.close(wake_read);os.close(wake_write)
    return 0

if __name__=='__main__':sys.exit(main())

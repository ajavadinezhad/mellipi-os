"""One event-driven swayidle child for Orbit's user-selected lock/display policy."""
import os,shlex,shutil,subprocess,select,sys,time
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot
ROOT=Path(__file__).resolve().parent
REAL_POPEN=subprocess.Popen

def spawn_timer(command,environment,spawn):
    if not sys.platform.startswith('linux'):raise ValueError('Safe idle timer lifetime requires Linux')
    wrapped=['/usr/bin/python3',str(ROOT/'idle_child.py'),str(os.getpid())]
    # An exec-close pipe reports wrapper/prctl/exec failures without a long-lived
    # helper or an inherited stdout/stderr pipe. Fake launchers need no OS FDs.
    if spawn is not REAL_POPEN:return spawn([*wrapped,*command],env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    read,write=os.pipe2(os.O_CLOEXEC);process=None
    try:
        process=spawn([*wrapped,'--ready-fd',str(write),*command],env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(write,))
        os.close(write);write=None;deadline=time.monotonic()+2;error=b''
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([read],[],[],remaining)[0]:raise ValueError('Idle timer startup did not confirm readiness')
            part=os.read(read,1024)
            if not part:break
            error=(error+part)[:1024]
        if error:raise ValueError(error.decode('utf-8','replace'))
        if process.poll() not in (None,0):raise ValueError('Idle timer exited during startup')
        return process
    except Exception:
        if process is not None:
            try:process.terminate();process.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired):
                try:process.kill()
                except OSError:pass
        raise
    finally:
        os.close(read)
        if write is not None:os.close(write)

def policy_command(values,native=False):
    enabled=values.get('idleLockEnabled',True);before=values.get('lockBeforeSleep',True)
    minutes=values.get('idleLockMinutes',10);off=values.get('displayOffMinutes',0)
    if type(enabled) is not bool or type(before) is not bool or type(minutes) is not int or not 1<=minutes<=120 or type(off) is not int or not 0<=off<=120:raise ValueError('Invalid idle policy')
    locker='/usr/bin/python3 '+shlex.quote(str(ROOT/'screen_lock.py'))
    args=['swayidle','-w']
    if enabled:args+=['timeout',str(minutes*60),locker]
    if off:
        # Leave time for the locker to secure the session before powering down.
        seconds=max(off*60,minutes*60+5) if enabled else off*60
        if native:
            power='/usr/bin/python3 '+shlex.quote(str(ROOT/'tools/native-output-power.py'))
            args+=['timeout',str(seconds),power+' off','resume',power+' on']
        else:args+=['timeout',str(seconds),'swaymsg "output * power off"','resume','swaymsg "output * power on"']
    if before:args+=['before-sleep',locker]
    return args if len(args)>2 else []

def legacy_idle_processes(environment,proc_root=Path('/proc')):
    """Find only this session's old autostart-owned Orbit idle process."""
    socket=environment.get('SWAYSOCK');found=[]
    if not socket:return found
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():continue
        try:
            if proc.stat().st_uid!=os.getuid():continue
            args=[a.decode() for a in (proc/'cmdline').read_bytes().split(b'\0') if a]
            if not args or Path(args[0]).name!='swayidle' or not any(str(ROOT/'screen_lock.py') in a for a in args):continue
            env=dict(a.split(b'=',1) for a in (proc/'environ').read_bytes().split(b'\0') if b'=' in a)
            if env.get(b'SWAYSOCK')!=socket.encode():continue
            pid=int(proc.name);parent=int(next(v for v in (proc/'status').read_text().splitlines() if v.startswith('PPid:')).split()[1])
            parent_args=(proc_root/str(parent)/'cmdline').read_bytes().split(b'\0')
            if str(ROOT/'session/autostart.py').encode() not in parent_args:continue
            found.append((pid,args))
        except (OSError,ValueError,UnicodeError):pass
    return found

def retire_legacy_idle(environment):
    import signal
    for pid,args in legacy_idle_processes(environment):
        try:
            # Recheck identity immediately before signalling; no process groups.
            proc=Path('/proc')/str(pid);current=[a.decode() for a in (proc/'cmdline').read_bytes().split(b'\0') if a]
            env=dict(a.split(b'=',1) for a in (proc/'environ').read_bytes().split(b'\0') if b'=' in a)
            if current==args and proc.stat().st_uid==os.getuid() and env.get(b'SWAYSOCK')==environment.get('SWAYSOCK','').encode():os.kill(pid,signal.SIGTERM)
        except (OSError,UnicodeError):pass

class IdlePolicy(QObject):
    changed=Signal();notice=Signal(str)
    def __init__(self,preferences,enabled=True,spawn=None,environment=None,availability=None):
        super().__init__();self.preferences=preferences;self.environment=dict(os.environ if environment is None else environment)
        self.enabled=bool(enabled and (self.environment.get('SWAYSOCK') or self.environment.get('ORBIT_NATIVE_CONTROL')) and not self.environment.get('ORBIT_NESTED'));self.spawn=spawn or subprocess.Popen
        self.availability=availability or (lambda:bool(shutil.which('swayidle') and Path('/etc/pam.d/swaylock').is_file() and __import__('screen_lock').locker_binary()))
        self.native=bool(self.environment.get('ORBIT_NATIVE_CONTROL'))
        self.native_capabilities={}
        if self.native:
            try:
                from native_compositor import NativeCompositor
                status=NativeCompositor(self.environment['ORBIT_NATIVE_CONTROL']).status();self.native_capabilities=dict(status.get('capabilities',{}),**status.get('control_capabilities',{}))
            except (OSError,ValueError,RuntimeError):pass
            prerequisites=self.availability
            self.availability=lambda: bool(self.native_capabilities.get('secure_lock') and self.native_capabilities.get('idle_notify') and prerequisites())
        self.process=None;self.current=None;self.error='';self.closed=False;self.migrated=False
        self.apply()
    state=Property('QVariantMap',lambda self:dict(available=self.enabled and self.availability(),running=self.process is not None and self.process.poll() is None,error=self.error),notify=changed)
    def _stop(self):
        process,self.process=self.process,None
        if process is not None:
            try:
                process.terminate();process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=2)
            except OSError:pass
    @Slot()
    def apply(self):
        if self.closed:return
        if not self.enabled:self.changed.emit();return
        try:
            command=policy_command(self.preferences.values,native=self.native)
            if self.native and self.preferences.values.get('displayOffMinutes',0) and (not self.native_capabilities.get('dpms') or not self.preferences.values.get('idleLockEnabled',True)):raise ValueError('Native display-off requires working DPMS and automatic screen locking')
            if command and not self.availability():raise ValueError('Native idle locking requires validated secure-lock and idle-notification support' if self.native else 'Install swayidle and the system screen-lock prerequisites before enabling this policy')
            if self.current==command and (not command or self.process is not None and self.process.poll() is None):return
            if not self.migrated:
                if self.spawn is subprocess.Popen:retire_legacy_idle(self.environment)
                self.migrated=True
            self._stop();self.current=None
            if command:
                env={k:v for k,v in self.environment.items() if not k.startswith('ORBIT_')}
                if self.native:env['ORBIT_NATIVE_CONTROL']=self.environment['ORBIT_NATIVE_CONTROL']
                for key in ('QT_WAYLAND_SHELL_INTEGRATION','QT_QPA_PLATFORM','QT_QUICK_BACKEND'):env.pop(key,None)
                # The wrapper execs the timer, so it consumes no extra idle
                # process and the timer dies even if Orbit itself is SIGKILLed.
                self.process=spawn_timer(command,env,self.spawn)
            self.current=command;self.error=''
        except (OSError,ValueError,subprocess.SubprocessError) as error:self.error=str(error);self.notice.emit(self.error)
        self.changed.emit()
    def close(self):self.closed=True;self._stop()

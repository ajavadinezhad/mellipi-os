"""Bounded XDG login autostart; discovery is read-only, launch is explicit.

GIO owns Desktop Entry Exec quoting/field codes and D-Bus activation. We never
interpolate commands or use a shell ourselves. Desktop files can explicitly ask
for a shell (as many distribution entries do); that remains their application.
"""
import configparser
import hashlib
import itertools
import os
import shlex
import shutil
import stat
import sys
from pathlib import Path

MAX_FILE_BYTES=128*1024
MAX_FILES=2048
MAX_DIRECTORIES=32
# Orbit owns its compositor, settings, notifications, networking UI and idle lock.
# Starting another desktop's session owner/lock agent can take over or lock out
# this session. User applications, IME launchers and accessibility tools remain.
OWNED_EXECUTABLES=frozenset(('orbit-shell','orbit-compositor','sway','swayidle','swaylock',
 'light-locker','xscreensaver','xfce4-session','xfwm4','xfsettingsd',
 'xfce4-power-manager','xfce4-notifyd','nm-applet','blueman-applet'))
INTERPRETERS=frozenset(('python','python3','bash','sh','dash','perl','ruby','node','env'))
POLKIT_EXECUTABLES=frozenset(('polkit-gnome-authentication-agent-1','polkit-mate-authentication-agent-1',
 'lxpolkit','lxqt-policykit-agent','polkit-kde-authentication-agent-1'))

def log(name,reason):
    # Never log Exec lines: user-provided entries may contain credentials.
    print('Mellipi autostart: '+str(name).replace('\n',' ')[:180]+': '+reason,file=sys.stderr,flush=True)

def directories(environment):
    home=Path(environment.get('HOME',str(Path.home())))
    config=environment.get('XDG_CONFIG_HOME') or str(home/'.config')
    configs=environment.get('XDG_CONFIG_DIRS') or '/etc/xdg'
    seen=set();result=[]
    for value in itertools.islice(itertools.chain((config,),configs.split(':')),MAX_DIRECTORIES):
        if not value or not Path(value).is_absolute():continue
        path=Path(value)/'autostart'
        if path not in seen:seen.add(path);result.append(path)
    return result

def selected_files(environment):
    """Highest-priority filename masks every lower entry, even if invalid/Hidden."""
    selected={}
    for directory in directories(environment):
        try:
            with os.scandir(directory) as scan:
                names=sorted(entry.name for entry in itertools.islice(scan,MAX_FILES) if entry.name.endswith('.desktop'))
        except OSError:continue
        for name in names:
            if name not in selected:selected[name]=directory/name
            if len(selected)>=MAX_FILES:return selected
    return selected

def read_entry(path):
    # Following standard symlink entries is allowed; a FIFO/device is never read.
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_FILE_BYTES:raise ValueError('oversized/nonregular entry')
        raw=stream.read(MAX_FILE_BYTES+1)
    if len(raw)>MAX_FILE_BYTES:raise ValueError('oversized entry')
    parser=configparser.ConfigParser(interpolation=None,strict=True,delimiters=('=',),comment_prefixes=('#',),inline_comment_prefixes=None)
    parser.optionxform=str;parser.read_string(raw.decode('utf-8'))
    if not parser.has_section('Desktop Entry'):raise ValueError('missing Desktop Entry')
    return dict(parser.items('Desktop Entry'))

def boolean(entry,key):
    value=entry.get(key,'false')
    if value not in ('true','false'):raise ValueError('invalid '+key)
    return value=='true'

def eligible(entry,environment):
    if entry.get('Type')!='Application':return 'not an application'
    if boolean(entry,'Hidden'):return 'disabled'
    # Widely-used opt-out retained in addition to the portable XDG keys.
    if 'X-GNOME-Autostart-enabled' in entry and not boolean(entry,'X-GNOME-Autostart-enabled'):return 'disabled'
    desktops=set(filter(None,environment.get('XDG_CURRENT_DESKTOP','Orbit').split(':')))
    only=set(filter(None,entry.get('OnlyShowIn','').split(';')))
    never=set(filter(None,entry.get('NotShowIn','').split(';')))
    if only and never:return 'conflicting desktop conditions'
    if only and not only.intersection(desktops):return 'another desktop'
    if never.intersection(desktops):return 'excluded desktop'
    candidate=entry.get('TryExec','')
    if candidate:
        if '/' in candidate:
            if not Path(candidate).is_absolute() or not Path(candidate).is_file() or not os.access(candidate,os.X_OK):return 'TryExec unavailable'
        elif not shutil.which(candidate,path=environment.get('PATH',os.defpath)):return 'TryExec unavailable'
    if not entry.get('Exec') and not boolean(entry,'DBusActivatable'):return 'no launch target'
    return None

def command_identity(entry):
    """Only used for duplicate suppression; never executes parsed tokens."""
    try:parts=shlex.split(entry.get('Exec',''))
    except ValueError:return None
    if not parts:return None
    # Treat env wrappers as their application, including env VAR=value app.
    if Path(parts[0]).name=='env':
        parts=parts[1:]
        while parts and (parts[0].startswith('-') or '=' in parts[0]):parts=parts[1:]
    return Path(parts[0]).name if parts else None

def same_graphical_session(peer,environment):
    """A permission agent in another login cannot authenticate this session."""
    session=environment.get('XDG_SESSION_ID');other=peer.get('XDG_SESSION_ID')
    if session and other:return session==other
    display=environment.get('WAYLAND_DISPLAY')
    if display:
        return peer.get('WAYLAND_DISPLAY')==display and bool(environment.get('XDG_RUNTIME_DIR')) and peer.get('XDG_RUNTIME_DIR')==environment['XDG_RUNTIME_DIR']
    display=environment.get('DISPLAY')
    return bool(display) and peer.get('DISPLAY')==display

def running_executables(proc=Path('/proc'),environment=None,names=None):
    result=set()
    try:
        with os.scandir(proc) as scan:
            entries=list(itertools.islice(scan,32768))
    except OSError:return result
    for entry in entries:
        if not entry.name.isdigit():continue
        try:
            path=Path(entry.path)
            if path.stat().st_uid!=os.getuid():continue
            with (path/'cmdline').open('rb') as stream:command=stream.read(4096).split(b'\0',1)[0]
            if not command:continue
            name=Path(os.fsdecode(command)).name
            if names is not None and name not in names:continue
            if environment is not None:
                # Inspect only explicitly selected agents; retain routing keys,
                # never log or keep credentials from their environment.
                with (path/'environ').open('rb') as stream:raw=stream.read(65537)
                if len(raw)>65536:continue
                keys={b'XDG_SESSION_ID',b'WAYLAND_DISPLAY',b'XDG_RUNTIME_DIR',b'DISPLAY'}
                peer={os.fsdecode(k):os.fsdecode(v) for part in raw.split(b'\0') if b'=' in part for k,v in [part.split(b'=',1)] if k in keys}
                if not same_graphical_session(peer,environment):continue
            result.add(name)
        except OSError:continue
    return result

def claim_session(environment):
    """Once per real compositor socket lifetime, including supervisor restarts."""
    runtime=Path(environment.get('XDG_RUNTIME_DIR','/run/user/'+str(os.getuid())))
    info=runtime.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:raise OSError('unsafe runtime directory')
    socket_path=environment.get('ORBIT_NATIVE_CONTROL') or environment.get('SWAYSOCK') or environment.get('ORBIT_NATIVE_SOCK')
    if not socket_path:
        display=environment.get('WAYLAND_DISPLAY','')
        socket_path=str(runtime/display) if display and not Path(display).is_absolute() else display
    if not socket_path:raise OSError('no compositor socket identity')
    identity=Path(socket_path).stat()
    key=hashlib.sha256((str(socket_path)+':'+str(identity.st_dev)+':'+str(identity.st_ino)+':'+str(identity.st_ctime_ns)).encode()).hexdigest()[:32]
    marker=runtime/('orbit-autostart-'+key)
    try:fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
    except FileExistsError:return False
    with os.fdopen(fd,'w') as stream:stream.write(str(os.getpid())+'\n')
    return True

def launch_autostart(launch,environment=None,reserved_commands=(),claim=claim_session):
    environment=dict(os.environ if environment is None else environment)
    if environment.get('ORBIT_NESTED'):return []
    gio=shutil.which('gio',path=environment.get('PATH',os.defpath))
    if not gio:log('session','GIO unavailable; startup entries skipped');return []
    try:
        if not claim(environment):return []
    except OSError as error:log('session','cannot safely claim startup: '+str(error));return []
    reserved=set(OWNED_EXECUTABLES)
    reserved.update(Path(command[0]).name for command in reserved_commands if command)
    running=running_executables();launched=[];polkit_started=bool(POLKIT_EXECUTABLES.intersection(reserved|running))
    for name,path in sorted(selected_files(environment).items()):
        try:
            entry=read_entry(path);reason=eligible(entry,environment);identity=command_identity(entry)
            if reason:continue
            if identity in reserved:continue
            if identity in POLKIT_EXECUTABLES and polkit_started:continue
            # Existing user daemons are normally singletons. Keyring --start is
            # deliberately allowed: it enables individual components of a daemon
            # already unlocked by PAM, rather than creating another daemon.
            if identity in running and identity!='gnome-keyring-daemon' and identity not in INTERPRETERS:continue
            process=launch([gio,'launch',str(path)],environment=environment)
            if process is None:continue
            launched.append(name)
            if identity and identity!='gnome-keyring-daemon' and identity not in INTERPRETERS:reserved.add(identity)
            if identity in POLKIT_EXECUTABLES:polkit_started=True
            log(name,'launched')
        except (OSError,ValueError,UnicodeError,configparser.Error) as error:log(name,'skipped invalid/unavailable entry ('+type(error).__name__+')')
    return launched

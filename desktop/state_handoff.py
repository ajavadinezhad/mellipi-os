"""One-shot, fingerprint-guarded handoff from an active development profile.

Only allowlisted state is read; no programs or commands are migrated/executed.
The installed profile is independent after consuming its private marker.
"""
import hashlib,json,os,shutil,sqlite3,stat,tempfile,time
from pathlib import Path
DATA_FILES=('fold-state.json','desktop-layout.json','shortcuts.conf','input.conf','outputs-native.json','brightness-target.json','orbit.sqlite3')
CONFIG_FILES=('settings.json','layouts.json','app-usage.json')

def digest(path):
    try:
        if path.is_symlink() or not path.is_file():return None
        h=hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
        return h.hexdigest()
    except FileNotFoundError:return None

def roots(environment):return Path(environment['ORBIT_DATA']),Path(environment['ORBIT_SETTINGS_FILE']).parent

def targets(environment):
    data,config=roots(environment)
    return {**{name:data/name for name in DATA_FILES},**{name:(Path(environment['ORBIT_SETTINGS_FILE']) if name=='settings.json' else config/name) for name in CONFIG_FILES}}

def atomic_json(path,value):
    fd,name=tempfile.mkstemp(prefix='.handoff-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:json.dump(value,out);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def arm(source,environment,desktop_layout=None):
    data,config=roots(environment);source=Path(source).absolute()
    if not source.is_dir() or source.is_symlink() or source.stat().st_uid!=os.getuid():raise ValueError('Choose an owned source state directory')
    if (data/'native-session.log').exists():raise ValueError('Installed profile has already been used; preserve it')
    for directory in (data,config):
        directory.mkdir(parents=True,mode=0o700,exist_ok=True)
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Installed state directory must be private')
    marker=dict(version=1,source=str(source),data=str(data),config=str(config),expected={name:digest(path) for name,path in targets(environment).items()})
    if desktop_layout is not None:marker['desktop_layout']=str(Path(desktop_layout).absolute())
    atomic_json(data/'pending-state-handoff.json',marker)

def consume(environment):
    data,config=roots(environment);path=data/'pending-state-handoff.json'
    try:fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return dict(copied=[],preserved=[])
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>16384:raise ValueError('Unsafe state handoff marker')
        raw=source.read(16385)
        if len(raw)>16384:raise ValueError('Oversized state handoff marker')
        marker=json.loads(raw)
    dests=targets(environment)
    if not isinstance(marker,dict) or marker.get('version')!=1 or marker.get('data')!=str(data) or marker.get('config')!=str(config) or not isinstance(marker.get('expected'),dict) or set(marker['expected'])!=set(dests):raise ValueError('Invalid state handoff marker')
    if not isinstance(marker.get('source'),str):raise ValueError('Invalid source state directory')
    source=Path(marker['source'])
    if not source.is_absolute() or source.is_symlink() or not source.is_dir() or source.stat().st_uid!=os.getuid():raise ValueError('Source state directory is unavailable')
    copied=[];preserved=[];backup=data/'migration-backups'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    for name,dst in dests.items():
        src=source/name
        if name=='desktop-layout.json' and not src.exists() and marker.get('desktop_layout'):src=Path(marker['desktop_layout'])
        if not src.is_file() or src.is_symlink() or src.stat().st_uid!=os.getuid():continue
        expected=marker['expected'][name]
        if expected is not None and (not isinstance(expected,str) or len(expected)!=64):raise ValueError('Invalid destination fingerprint')
        if dst.is_symlink() or digest(dst)!=expected or (name=='orbit.sqlite3' and Path(str(dst)+'-wal').exists()):preserved.append(name);continue
        if digest(src)==expected:continue
        fd,temporary=tempfile.mkstemp(prefix='.handoff-',dir=dst.parent);os.close(fd);temporary=Path(temporary)
        try:
            if name=='orbit.sqlite3':
                with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(temporary) as new:old.backup(new)
            else:
                shutil.copyfile(src,temporary)
                if name.endswith('.json'):json.loads(temporary.read_text())
            temporary.chmod(0o600)
            with temporary.open('rb') as stream:os.fsync(stream.fileno())
            # Recheck after copying, so a new destination edit wins the race.
            if dst.is_symlink() or digest(dst)!=expected:preserved.append(name);continue
            if dst.exists():
                backup.mkdir(parents=True,mode=0o700,exist_ok=True);backup.chmod(0o700)
                shutil.copy2(dst,backup/name);(backup/name).chmod(0o600)
            os.replace(temporary,dst);copied.append(name)
        finally:temporary.unlink(missing_ok=True)
    path.unlink()
    return dict(copied=copied,preserved=preserved)

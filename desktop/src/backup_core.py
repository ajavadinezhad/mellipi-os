"""Explicit, portable backups. Never follows symlinks or overwrites restored files.

The backup is an ordinary private directory, not an executable archive. Personal
files are opt-in; their paths are always recreated below a fresh restore folder.
Desktop settings can be queued for the next real login with fingerprint guards.
"""
import hashlib,json,os,re,shutil,stat,tempfile,time,uuid
from pathlib import Path

MAX_FILES=50000
MAX_BYTES=32*1024**3
MAX_JSON=16*1024**2
CONFIG=('settings.json','layouts.json','app-usage.json')
DATA=('fold-state.json','desktop-layout.json','outputs-native.json','brightness-target.json')

def roots(environment):
    home=Path(environment.get('HOME',str(Path.home())))
    config=Path(environment.get('ORBIT_SETTINGS_FILE',str(Path(environment.get('XDG_CONFIG_HOME',home/'.config'))/'abstract/settings.json'))).parent
    data=Path(environment.get('ORBIT_DATA',str(Path(environment.get('XDG_DATA_HOME',home/'.local/share'))/'abstract')))
    return config,data

def settings_paths(environment):
    config,data=roots(environment)
    return {**{'config/'+n:(Path(environment['ORBIT_SETTINGS_FILE']) if n=='settings.json' and environment.get('ORBIT_SETTINGS_FILE') else config/n) for n in CONFIG},**{'data/'+n:data/n for n in DATA}}

def _regular(path):
    p=Path(path);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):os.close(fd);raise ValueError('Only regular files can be backed up')
    return fd

def _safe_chain(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Symlinks are not followed')
    # Normalize only after checking each original component, so neither a
    # lexical '..' nor a symlink can bypass recursive-destination protection.
    return Path(os.path.normpath(path))

def _hash_stream(source,cancelled=lambda:False,limit=MAX_BYTES):
    h=hashlib.sha256();read=0
    for block in iter(lambda:source.read(1024*1024),b''):
        if cancelled():raise InterruptedError('Backup verification cancelled')
        read+=len(block)
        if read>limit:raise ValueError('File grew past its recorded size')
        h.update(block)
    return h.hexdigest()

def digest(path,cancelled=lambda:False):
    try:
        with os.fdopen(_regular(path),'rb') as src:return _hash_stream(src,cancelled)
    except FileNotFoundError:return None

def _json_write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:os.fchmod(f.fileno(),0o600);json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())

def create_backup(parent,environment,personal=(),cancelled=lambda:False):
    parent=_safe_chain(parent)
    if not parent.is_dir():raise ValueError('Choose an existing backup destination')
    selected=[]
    for value in personal:
        source=_safe_chain(value)
        if not source.exists():raise ValueError('A selected file is no longer available')
        # A destination under an included folder would recursively back up itself.
        if source.is_dir() and (parent==source or source in parent.parents):raise ValueError('Choose a destination outside the selected folder')
        selected.append(source)
    stage=Path(tempfile.mkdtemp(prefix='.mellipi-backup-',dir=parent));stage.chmod(0o700)
    rows=[];total=0
    def add_directory(source,name):
        if cancelled():raise InterruptedError('Backup cancelled')
        if len(rows)>=MAX_FILES:raise ValueError('Backup exceeds the 50,000-entry limit; choose smaller folders')
        source=_safe_chain(source);metadata=source.stat()
        if not stat.S_ISDIR(metadata.st_mode):raise ValueError('Selected folder changed during backup')
        target=stage/'files'/name;target.mkdir(parents=True,exist_ok=True,mode=0o700)
        rows.append({'path':name,'kind':'personal','type':'directory','bytes':0,'mode':0o700,'mtime_ns':metadata.st_mtime_ns})
    def add(source,name,kind):
        nonlocal total
        if cancelled():raise InterruptedError('Backup cancelled')
        if len(rows)>=MAX_FILES:raise ValueError('Backup exceeds the 50,000-entry limit; choose smaller folders')
        source=_safe_chain(source)
        with os.fdopen(_regular(source),'rb') as src:
            metadata=os.fstat(src.fileno());size=metadata.st_size
            if total+size>MAX_BYTES:raise ValueError('Backup exceeds the 32 GiB limit; choose smaller folders')
            if kind=='settings':
                if size>MAX_JSON:raise ValueError('Desktop settings file is too large')
                raw=src.read();json.loads(raw);src.seek(0)
            dest=stage/'files'/name;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            h=hashlib.sha256();written=0
            with dest.open('xb') as out:
                os.fchmod(out.fileno(),0o600)
                for block in iter(lambda:src.read(1024*1024),b''):
                    if cancelled():raise InterruptedError('Backup cancelled')
                    written+=len(block)
                    if total+written>MAX_BYTES:raise ValueError('Selected files grew past the backup limit')
                    out.write(block);h.update(block)
                out.flush();os.fsync(out.fileno())
            mode=0o600|(metadata.st_mode&stat.S_IXUSR if kind=='personal' else 0)
            total+=written;rows.append({'path':name,'kind':kind,'type':'file','bytes':written,'sha256':h.hexdigest(),'mode':mode,'mtime_ns':metadata.st_mtime_ns})
    try:
        for name,source in settings_paths(environment).items():
            if source.exists() or source.is_symlink():add(source,'settings/'+name,'settings')
        for index,source in enumerate(selected):
            prefix=f'personal/{index:04d}/'+source.name
            if source.is_file():add(source,prefix,'personal')
            elif source.is_dir():
                for current,dirs,files in os.walk(source,followlinks=False):
                    current=Path(current);relative=current.relative_to(source);add_directory(current,prefix+('/'+str(relative) if relative.parts else ''))
                    for name in dirs:
                        if (Path(current)/name).is_symlink():raise ValueError('Selected folder contains a symlink; choose files explicitly')
                    for name in files:
                        file=Path(current)/name;add(file,prefix+'/'+str(file.relative_to(source)),'personal')
            else:raise ValueError('Choose regular files or folders')
        _json_write(stage/'manifest.json',{'format':'mellipi-backup','version':2,'created':int(time.time()),'files':rows,'bytes':total})
        final=parent/('Mellipi-backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);stage.rename(final)
        return {'path':str(final),'files':sum(r['type']=='file' for r in rows),'directories':sum(r['type']=='directory' for r in rows),'bytes':total}
    except BaseException:shutil.rmtree(stage);raise

def inspect_backup(directory,cancelled=lambda:False):
    directory=_safe_chain(directory)
    manifest=_safe_chain(directory/'manifest.json')
    with os.fdopen(_regular(manifest),'rb') as source:
        if os.fstat(source.fileno()).st_size>MAX_JSON:raise ValueError('Backup manifest is too large')
        data=json.load(source)
    if not isinstance(data,dict) or data.get('format')!='mellipi-backup' or type(data.get('version')) is not int or data['version'] not in (1,2) or not isinstance(data.get('files'),list) or len(data['files'])>MAX_FILES:raise ValueError('Not a supported Mellipi backup')
    seen=set();total=0
    for row in data['files']:
        if cancelled():raise InterruptedError('Backup verification cancelled')
        if not isinstance(row,dict):raise ValueError('Invalid backup file record')
        name=row.get('path');kind=row.get('kind');size=row.get('bytes');checksum=row.get('sha256');entry_type=row.get('type','file')
        if not isinstance(name,str) or not name or '\\' in name or '\x00' in name or Path(name).is_absolute() or any(part in ('..','.') for part in name.split('/')) or '' in name.split('/') or name in seen:raise ValueError('Unsafe or duplicate backup path')
        if kind not in ('personal','settings') or not name.startswith(kind+'/') or type(size) is not int or size<0 or entry_type not in ('file','directory') or (data['version']==1 and entry_type!='file'):raise ValueError('Invalid backup metadata')
        if data['version']==2:
            mode=row.get('mode');mtime=row.get('mtime_ns')
            if type(mode) is not int or mode not in ((0o700,) if entry_type=='directory' else (0o600,0o700)) or type(mtime) is not int or not -(2**63)<=mtime<2**63 or (kind=='settings' and mode!=0o600):raise ValueError('Unsafe backup permissions or timestamp')
        if entry_type=='directory':
            if kind!='personal' or size!=0 or checksum is not None:raise ValueError('Invalid directory record')
            path=_safe_chain(directory/'files'/name)
            if not path.is_dir():raise ValueError('Backup directory is missing: '+name)
            seen.add(name);continue
        if not isinstance(checksum,str) or not re.fullmatch('[a-f0-9]{64}',checksum):raise ValueError('Invalid backup checksum')
        if kind=='settings' and (size>MAX_JSON or name.removeprefix('settings/') not in {*(f'config/{n}' for n in CONFIG),*(f'data/{n}' for n in DATA)}):raise ValueError('Unexpected or oversized desktop settings path')
        total+=size
        if total>MAX_BYTES:raise ValueError('Backup exceeds the restore limit')
        path=_safe_chain(directory/'files'/name)
        with os.fdopen(_regular(path),'rb') as source:
            if os.fstat(source.fileno()).st_size!=size or _hash_stream(source,cancelled,size)!=checksum:raise ValueError('Backup is damaged: '+name)
        seen.add(name)
    if data.get('bytes')!=total:raise ValueError('Backup size does not match its manifest')
    return data

def _restore_metadata(path,row,version):
    # Old manifests did not record metadata and keep the original safe defaults.
    mode=row['mode'] if version==2 else 0o600
    path.chmod(mode)
    if stat.S_IMODE(path.stat().st_mode)!=mode:raise ValueError('Restore destination cannot enforce owner-only permissions; choose a Linux filesystem')
    if version==2:os.utime(path,ns=(row['mtime_ns'],row['mtime_ns']),follow_symlinks=False)

def restore_files(directory,parent,cancelled=lambda:False):
    directory=_safe_chain(directory);data=inspect_backup(directory,cancelled);parent=_safe_chain(parent)
    if not parent.is_dir():raise ValueError('Choose an existing restore destination')
    stage=Path(tempfile.mkdtemp(prefix='.mellipi-restore-',dir=parent));stage.chmod(0o700)
    try:
        for row in data['files']:
            if cancelled():raise InterruptedError('Restore cancelled')
            src=_safe_chain(directory/'files'/row['path']);dest=stage/row['path'];dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if row.get('type','file')=='directory':dest.mkdir(mode=0o700,exist_ok=True);continue
            with os.fdopen(_regular(src),'rb') as source,dest.open('xb') as target:
                os.fchmod(target.fileno(),0o600)
                for block in iter(lambda:source.read(1024*1024),b''):
                    if cancelled():raise InterruptedError('Restore cancelled')
                    target.write(block)
            if digest(dest,cancelled)!=row['sha256']:raise ValueError('Backup changed during restore')
            _restore_metadata(dest,row,data['version'])
        # Child creation changes a directory's mtime. Apply it after all files,
        # deepest first, so empty and non-empty folders both round-trip.
        directories=sorted((r for r in data['files'] if r.get('type')=='directory'),key=lambda r:len(Path(r['path']).parts),reverse=True)
        for row in directories:_restore_metadata(stage/row['path'],row,data['version'])
        final=parent/('Mellipi-restored-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);stage.rename(final)
        return {'path':str(final),'files':sum(r.get('type','file')=='file' for r in data['files']),'directories':len(directories)}
    except BaseException:shutil.rmtree(stage);raise

def queue_settings_restore(directory,environment,cancelled=lambda:False):
    directory=_safe_chain(directory);manifest=inspect_backup(directory,cancelled);paths=settings_paths(environment);_,data=roots(environment);data=_safe_chain(data);data.mkdir(parents=True,exist_ok=True,mode=0o700)
    items=[r for r in manifest['files'] if r['kind']=='settings']
    if not items:raise ValueError('This backup contains no desktop settings')
    marker=data/'pending-settings-restore.json'
    # Capture desired bytes now: moving the removable backup later cannot change
    # what the user reviewed. Never retain an executable or arbitrary target path.
    if sum(r['bytes'] for r in items)>MAX_JSON-4096:raise ValueError('Desktop settings restore is too large')
    desired={}
    for row in items:
        with os.fdopen(_regular(_safe_chain(directory/'files'/row['path'])),'rb') as f:
            raw=f.read(MAX_JSON+1)
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Backup changed while scheduling restore')
        desired[row['path'].removeprefix('settings/')]=raw.decode('utf-8')
    for value in desired.values():json.loads(value)
    value={'version':1,'expected':{key:digest(_safe_chain(paths[key])) for key in desired},'desired':desired}
    fd,temporary=tempfile.mkstemp(prefix='.mellipi-settings-request-',dir=data)
    try:
        with os.fdopen(fd,'w') as target:json.dump(value,target);target.flush();os.fsync(target.fileno())
        os.link(temporary,marker)
    finally:Path(temporary).unlink(missing_ok=True)
    return {'queued':len(desired),'message':'Settings will restore at your next login. Changes made since scheduling are kept.'}

def consume_settings_restore(environment):
    """Call once before the shell starts, only for a real installed login."""
    _,data=roots(environment);marker=_safe_chain(data/'pending-settings-restore.json')
    if not marker.exists():return {'restored':[],'preserved':[]}
    with os.fdopen(_regular(marker),'rb') as f:
        info=os.fstat(f.fileno())
        if info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>MAX_JSON:raise ValueError('Unsafe settings restore request')
        request=json.load(f)
    paths=settings_paths(environment)
    if request.get('version')!=1 or not isinstance(request.get('desired'),dict) or not isinstance(request.get('expected'),dict) or set(request['desired'])!=set(request['expected']) or not set(request['desired'])<=set(paths):raise ValueError('Invalid settings restore request')
    for key,value in request['desired'].items():
        if not isinstance(value,str):raise ValueError('Invalid restored settings')
        json.loads(value)
        expected=request['expected'][key]
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected)):raise ValueError('Invalid settings fingerprint')
    restored=[];preserved=[];history=data/('before-settings-restore-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    for key,value in request['desired'].items():
        target=_safe_chain(paths[key])
        if digest(target)!=request['expected'][key]:preserved.append(key);continue
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if target.exists():
            history.mkdir(mode=0o700,exist_ok=True)
            backup=history/key;backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copyfile(target,backup);backup.chmod(0o600)
        fd,tmp=tempfile.mkstemp(prefix='.mellipi-restore-',dir=target.parent)
        try:
            with os.fdopen(fd,'w') as f:f.write(value);f.flush();os.fsync(f.fileno())
            if target.is_symlink() or digest(target)!=request['expected'][key]:preserved.append(key);continue
            os.replace(tmp,target);restored.append(key)
        finally:Path(tmp).unlink(missing_ok=True)
    marker.unlink();return {'restored':restored,'preserved':preserved}

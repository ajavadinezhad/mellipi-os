"""A bounded, explicit record of working desktop package versions.

Recovery uses APT's configured signed repositories. It never executes a stored
command, consumes an arbitrary .deb, assumes Btrfs, or restarts the session.
"""
import json,os,re,shlex,stat,subprocess,tempfile,time
from pathlib import Path

PACKAGES=('mellipi-shell','mellipi-desktop','abstract-shell','abstract-desktop')
VERSION=re.compile(r'[0-9][A-Za-z0-9.+:~\-]{0,99}\Z')

def validate_specs(specs):
    if not isinstance(specs,list) or not specs or len(specs)>4:raise ValueError('Choose one to four desktop packages')
    seen=set();result=[]
    for value in specs:
        if not isinstance(value,str) or value.count('=')!=1:raise ValueError('Use package=version')
        name,version=value.split('=')
        if name not in PACKAGES or name in seen or not VERSION.fullmatch(version):raise ValueError('Only known desktop packages and exact versions are accepted')
        seen.add(name);result.append(value)
    if 'mellipi-shell' not in seen:raise ValueError('A Mellipi shell version is required')
    return result

def installed_versions(runner=subprocess.run):
    rows=[]
    for name in PACKAGES:
        result=runner(['dpkg-query','-W','-f=${db:Status-Status}\t${Version}',name],text=True,capture_output=True,timeout=5)
        if result.returncode:continue
        fields=result.stdout.strip().split('\t')
        if len(fields)==2 and fields[0]=='installed' and VERSION.fullmatch(fields[1]):rows.append(name+'='+fields[1])
    return validate_specs(rows)

def checkpoint_path(environment):
    home=Path(environment.get('HOME',str(Path.home())))
    return Path(environment.get('XDG_STATE_HOME',home/'.local/state'))/'mellipi/recovery.json'

def save_checkpoint(environment,runner=subprocess.run):
    specs=installed_versions(runner);path=checkpoint_path(environment)
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('Recovery path must not contain symlinks')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.working-version-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump({'version':1,'saved':int(time.time()),'packages':specs},f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)
    return load_checkpoint(environment)

def load_checkpoint(environment):
    path=checkpoint_path(environment)
    try:fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    except FileNotFoundError:return {'available':False,'packages':[],'command':''}
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>16384:raise ValueError('Unsafe working-version record')
        row=json.load(f)
    if not isinstance(row,dict) or row.get('version')!=1:raise ValueError('Invalid working-version record')
    specs=validate_specs(row.get('packages'))
    return {'available':True,'packages':specs,'saved':row.get('saved',0),'command':'sudo mellipi-recover --restore '+' '.join(shlex.quote(v) for v in specs)}

def restore_command(specs):
    # APT resolves and authenticates packages through trusted configured sources;
    # never install user-supplied files or silently accept unauthenticated data.
    return ['/usr/bin/apt-get','--allow-downgrades','install',*validate_specs(specs)]

def recovery_environment(environment):
    """Do not forward user APT_CONFIG, dpkg overrides or GUI/session secrets."""
    safe={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','HOME':'/root','USER':'root','LOGNAME':'root','LANG':'C.UTF-8'}
    term=environment.get('TERM','')
    if re.fullmatch(r'[A-Za-z0-9._+\-]{1,64}',term):safe['TERM']=term
    return safe

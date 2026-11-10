#!/usr/bin/python3 -I
"""Move only the previously managed project source; never refresh or restart."""
import json,os,stat,subprocess,tempfile
from pathlib import Path

FINGERPRINT='7D0FC30A9F2B9957B2970E3BB6B1D6FE6A4682AF'
OLD_URI='https://ajavadinezhad.github.io/abstract-os/apt'
NEW_URI='https://ajavadinezhad.github.io/mellipi-os/apt'
KEY='/usr/share/keyrings/mellipi-archive-keyring.gpg'
EXPECTED=f'Types: deb\nURIs: {NEW_URI}\nSuites: noble\nComponents: main\nArchitectures: amd64\nSigned-By: {KEY}\n'

def public_fingerprint(path):
    with tempfile.TemporaryDirectory(prefix='mellipi-key-check-') as home:
        result=subprocess.check_output(['/usr/bin/gpg','--homedir',home,'--batch','--with-colons','--show-keys',str(path)],text=True,stderr=subprocess.DEVNULL,timeout=10)
    rows=result.splitlines()
    if len([r for r in rows if r.startswith('pub:')])!=1:return None
    return next((r.split(':')[9] for r in rows if r.startswith('fpr:')),None)

def safe_file(path,uid):
    info=path.lstat()
    return stat.S_ISREG(info.st_mode) and info.st_uid==uid and not info.st_mode&0o022

def migrate(root=Path('/'),reader=public_fingerprint,uid=0):
    root=Path(root);old=root/'etc/apt/sources.list.d/abstract.sources';new=old.with_name('mellipi.sources')
    if not old.exists() and not old.is_symlink():return 'not-needed'
    if not safe_file(old,uid):return 'kept-custom-source'
    fields={}
    for line in old.read_text().splitlines():
        if not line or line.startswith('#'):continue
        if ':' not in line:return 'kept-custom-source'
        k,v=line.split(':',1)
        if k in fields:return 'kept-custom-source'
        fields[k]=v.strip()
    known={'Types':'deb','URIs':OLD_URI,'Suites':'noble','Components':'main','Architectures':'amd64','Signed-By':'/etc/apt/keyrings/abstract-archive-keyring.gpg'}
    if fields!=known:return 'kept-custom-source'
    old_key=root/known['Signed-By'].lstrip('/');new_key=root/KEY.lstrip('/')
    if not safe_file(old_key,uid) or not safe_file(new_key,uid) or reader(old_key)!=FINGERPRINT or reader(new_key)!=FINGERPRINT:return 'kept-custom-source'
    if new.exists() or new.is_symlink():
        if not safe_file(new,uid) or new.read_text()!=EXPECTED:return 'kept-custom-source'
    else:
        fd,name=tempfile.mkstemp(prefix='.mellipi-source-',dir=new.parent)
        try:
            with os.fdopen(fd,'w') as target:target.write(EXPECTED);target.flush();os.fsync(target.fileno())
            Path(name).chmod(0o644)
            os.link(name,new) # A concurrently created source is never replaced.
        finally:Path(name).unlink(missing_ok=True)
    archive=root/'var/lib/abstract/migrations';archive.mkdir(parents=True,exist_ok=True,mode=0o700)
    if archive.is_symlink() or archive.stat().st_uid!=uid:raise ValueError('Unsafe migration archive')
    backup=archive/'abstract.sources.pre-mellipi'
    if not backup.exists():
        fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as target:target.write(old.read_bytes())
    old.unlink()
    return 'migrated'

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run only through package configuration.')
    try:result=migrate()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Mellipi update-source migration deferred: '+str(error));raise SystemExit(0)
    if result=='migrated':print('Mellipi update source migrated; settings and running apps were preserved.')
    elif result=='kept-custom-source':print('Mellipi kept a customized update source. Use the signed source enrollment guide to migrate it.')

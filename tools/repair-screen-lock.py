#!/usr/bin/env python3
"""Check/repair only the stock Debian-family swaylock PAM include.

Uses the distribution's common-auth stack, as in Debian bug #1140096.
Never changes login/common-auth, overrides custom rules, or tests a password.
"""
import argparse,json,os,stat,tempfile
from pathlib import Path

EXPECTED='# Orbit screen locker: use the standard distribution password-authentication stack.\n@include common-auth\n'

def check(directory):
    directory=Path(directory);target=directory/'swaylock';common=directory/'common-auth'
    if target.is_symlink():raise ValueError('Refusing to replace a symlinked/custom swaylock policy')
    if not common.is_file():raise ValueError('The distribution common-auth policy is missing')
    content=target.read_text() if target.exists() else ''
    rules=[' '.join(line.split()) for line in content.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if rules in (['@include common-auth'],['auth include common-auth']):return dict(ready=True,legacy=False,path=str(target))
    if rules not in ([],['auth include login']):raise ValueError('Custom swaylock PAM policy found; no changes made')
    return dict(ready=False,legacy=bool(rules),path=str(target))

def repair(directory):
    directory=Path(directory);result=check(directory)
    if result['ready']:return {**result,'changed':False}
    target=directory/'swaylock';backup=directory/'swaylock.orbit-before-common-auth'
    if target.exists():
        original=target.read_bytes()
        try:
            descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            if backup.is_symlink() or not backup.is_file():raise ValueError('Unsafe backup path; no changes made')
        else:
            with os.fdopen(descriptor,'wb') as handle:handle.write(original);handle.flush();os.fsync(handle.fileno())
    descriptor,temporary=tempfile.mkstemp(prefix='.orbit-swaylock-',dir=directory)
    try:
        with os.fdopen(descriptor,'w') as handle:handle.write(EXPECTED);handle.flush();os.fsync(handle.fileno())
        os.chmod(temporary,0o644);os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return {**check(directory),'changed':True,'backup':str(backup) if backup.exists() else ''}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    try:
        if args.apply and os.geteuid()!=0:raise ValueError('Administrator access required: sudo python3 tools/repair-screen-lock.py --apply')
        result=repair('/etc/pam.d') if args.apply else check('/etc/pam.d')
        print(json.dumps(result));return 0 if result['ready'] else 1
    except (OSError,ValueError) as error:print(str(error));return 2

if __name__=='__main__':raise SystemExit(main())

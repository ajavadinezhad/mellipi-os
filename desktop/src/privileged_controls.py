"""Explicit administrator handoff to the root-owned installed battery helper.

Never runs a checkout helper as root. No password collection, sudo invocation,
resident process, privilege policy installation or hardware writes happen here.
"""
import json,os,stat,subprocess
from pathlib import Path
HELPER=Path('/usr/lib/abstract/abstract-charge-limit')
PKEXEC=Path('/usr/bin/pkexec')

def trusted_helper(path=HELPER):
    """Require the exact installed regular executable and trusted ancestors."""
    path=Path(path)
    if path!=HELPER or not path.is_absolute():return False
    try:
        if path.is_symlink() or path.resolve()!=path:return False
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or not info.st_mode&0o111:return False
        for parent in path.parents:
            info=parent.stat()
            if parent.is_symlink() or info.st_uid!=0 or info.st_mode&0o022:return False
        return True
    except OSError:return False

def charge_limit_helper_available():
    try:
        info=PKEXEC.stat()
        pkexec_ok=PKEXEC.is_file() and not PKEXEC.is_symlink() and info.st_uid==0 and not info.st_mode&0o022 and bool(info.st_mode&0o111)
    except OSError:pkexec_ok=False
    return trusted_helper() and pkexec_ok

def _run(args,runner=subprocess.run):
    # pkexec sanitizes its privileged environment; the helper additionally uses
    # isolated Python. Limit captured diagnostics and never request a password.
    result=runner(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=False,env={key:value for key,value in os.environ.items() if key in ('PATH','LANG','LANGUAGE','LC_ALL','LC_MESSAGES','DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','XDG_SESSION_ID','TERM')})
    if result.returncode:
        if result.returncode in (126,127):raise PermissionError('Authorization was canceled or unavailable; no changes were made')
        details=(result.stderr or result.stdout or b'Charge-limit helper failed').decode('utf-8','replace')[:300].strip()
        raise RuntimeError(details)
    if len(result.stdout)>65536:raise RuntimeError('Charge-limit helper returned an oversized response')
    try:value=json.loads(result.stdout)
    except (ValueError,TypeError) as error:raise RuntimeError('Charge-limit helper returned an invalid response') from error
    if not isinstance(value,dict) or not value.get('ok'):raise RuntimeError('Charge-limit operation did not complete')
    return value

def set_charge_limit_privileged(name,percent,expected_identity=None,persist=True,runner=subprocess.run):
    import re
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',name) or name in ('.','..'):raise ValueError('Choose a system battery')
    if type(percent) is not int or not 40<=percent<=100:raise ValueError('Charge limit must be between 40% and 100%')
    if not charge_limit_helper_available():raise PermissionError('The administrator charge-limit helper is not installed')
    probe=_run([str(HELPER),'--describe',name],runner)
    if expected_identity is not None and tuple(expected_identity)!=(probe.get('path'),probe.get('device'),probe.get('inode')):raise RuntimeError('Battery changed or was disconnected; choose it again')
    identity=probe.get('identity','')
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{64}',identity):raise RuntimeError('Battery identity could not be verified')
    args=[str(PKEXEC),str(HELPER),'--set',name,str(percent),'--identity',identity]
    if persist:args.append('--persist')
    return _run(args,runner)

def forget_charge_limit_privileged(name,runner=subprocess.run):
    import re
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',name) or name in ('.','..'):raise ValueError('Choose a system battery')
    if not charge_limit_helper_available():raise PermissionError('The administrator charge-limit helper is not installed')
    return _run([str(PKEXEC),str(HELPER),'--forget',name],runner)

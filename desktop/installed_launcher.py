#!/usr/bin/env python3
"""Packaged entrypoints: immutable program files, private XDG user state."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def user_environment(environment=None):
    env=dict(os.environ if environment is None else environment)
    home=Path(env.get('HOME') or str(Path.home()))
    if not home.is_absolute():home=Path.home()
    env['HOME']=str(home)
    for key,suffix in (('XDG_DATA_HOME','.local/share'),('XDG_CONFIG_HOME','.config'),('XDG_STATE_HOME','.local/state'),('XDG_CACHE_HOME','.cache')):
        value=env.get(key,'')
        env[key]=value if value and Path(value).is_absolute() else str(home/suffix)
    defaults={'ORBIT_DATA':str(Path(env['XDG_DATA_HOME'])/'abstract'),'ORBIT_SETTINGS_FILE':str(Path(env['XDG_CONFIG_HOME'])/'abstract/settings.json')}
    for key,default in defaults.items():
        value=env.get(key) or default
        if not Path(value).is_absolute():raise ValueError(key+' must be an absolute path')
        env[key]=value
    env['ORBIT_FOLD_STATE']=env.get('ORBIT_FOLD_STATE') or str(Path(env['ORBIT_DATA'])/'fold-state.json')
    if not Path(env['ORBIT_FOLD_STATE']).is_absolute():raise ValueError('ORBIT_FOLD_STATE must be an absolute path')
    return env

def main():
    if len(sys.argv)<2 or sys.argv[1] not in ('session','control'):raise SystemExit('Expected session or control')
    kind,*args=sys.argv[1:]
    try:env=user_environment()
    except ValueError as error:raise SystemExit(str(error))
    if kind=='session':
        env['ORBIT_INSTALLED_SESSION']='1'
        if any(flag in args for flag in ('--check','--check-login','--help','-h')):
            os.execve('/usr/bin/python3',['/usr/bin/python3',str(ROOT/'session/native_session.py'),*args],env)
        # Nested previews use their own temporary data and preferences.
        if '--nested' in args:
            import tempfile
            with tempfile.TemporaryDirectory(prefix='abstract-preview-') as directory:
                env.update(ORBIT_DATA=directory,ORBIT_SETTINGS_FILE=str(Path(directory)/'settings.json'),ORBIT_FOLD_STATE=str(Path(directory)/'fold-state.json'))
                import subprocess
                return subprocess.call(['/usr/bin/python3',str(ROOT/'session/native_session.py'),*args],env=env,cwd=ROOT)
        Path(env['ORBIT_DATA']).mkdir(parents=True,mode=0o700,exist_ok=True)
        Path(env['ORBIT_SETTINGS_FILE']).parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        os.execve('/usr/bin/python3',['/usr/bin/python3',str(ROOT/'session/native_session.py'),*args],env)
    os.execve('/usr/bin/python3',['/usr/bin/python3',str(ROOT/'orbitctl.py'),*args],env)
if __name__=='__main__':sys.exit(main())

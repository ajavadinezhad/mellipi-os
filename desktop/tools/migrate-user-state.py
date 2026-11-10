#!/usr/bin/env python3
"""Explicit user-side checkout→installed Abstract migration; never overwrite.

Run when you are ready to switch installation. Existing source files are kept.
SQLite uses its backup API, so open data is copied consistently. No session,
app, hardware setting, clipboard or authentication state is changed.
"""
import argparse,os,shutil,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from installed_launcher import user_environment
FILES=('fold-state.json','desktop-layout.json','shortcuts.conf','input.conf','outputs-native.json','brightness-target.json')
CONFIG_FILES=('settings.json','layouts.json','app-usage.json')

def publish(src,dst,sqlite=False):
    dst.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.migration-',dir=dst.parent);temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as outgoing:
            if not sqlite:
                with src.open('rb') as incoming:shutil.copyfileobj(incoming,outgoing)
        if sqlite:
            with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(temporary) as new:old.backup(new)
        try:os.link(temporary,dst)
        except FileExistsError:return False
        return True
    finally:temporary.unlink(missing_ok=True)

def migrate(source,environment=None):
    source=Path(source).resolve();env=user_environment(environment)
    if not source.is_dir():raise ValueError('Choose the checkout data directory')
    destinations=[(source/name,Path(env['ORBIT_DATA'])/name) for name in FILES]
    config=Path(env['ORBIT_SETTINGS_FILE']).parent
    destinations.extend((source/name,Path(env['ORBIT_SETTINGS_FILE']) if name=='settings.json' else config/name) for name in CONFIG_FILES)
    copied=[];skipped=[]
    for src,dst in destinations:
        if not src.is_file() or src.is_symlink():continue
        if dst.exists() or dst.is_symlink():skipped.append(dst.name);continue
        (copied if publish(src,dst) else skipped).append(dst.name)
    src=source/'orbit.sqlite3';dst=Path(env['ORBIT_DATA'])/'orbit.sqlite3'
    if src.is_file() and not src.is_symlink():
        if dst.exists() or dst.is_symlink():skipped.append(dst.name)
        else:(copied if publish(src,dst,sqlite=True) else skipped).append(dst.name)
    return copied,skipped

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--from',dest='source',type=Path,required=True);args=parser.parse_args()
    if os.geteuid()==0:parser.error('Run as your desktop user, without sudo')
    try:copied,skipped=migrate(args.source)
    except (OSError,ValueError,sqlite3.Error) as error:raise SystemExit(str(error))
    print('Copied: '+(', '.join(copied) or 'nothing'));print('Existing files kept: '+(', '.join(skipped) or 'none'))
if __name__=='__main__':main()

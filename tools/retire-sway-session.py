#!/usr/bin/env python3
"""Remove only Orbit's retired Sway login files; preserve distro/Mint sessions."""
import argparse,configparser,json,os,shlex,stat,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=(Path('/usr/local/bin/orbit-session'),Path('/usr/share/wayland-sessions/orbit.desktop'))
def inspect(files=None,native=None,owner=0):
    files=FILES if files is None else files
    native=Path('/usr/share/wayland-sessions/orbit-native.desktop') if native is None else Path(native)
    if not native.is_file() or 'Exec=/usr/local/bin/orbit-native-session' not in native.read_text():raise ValueError('Native login registration must exist before retiring Sway')
    rows=[]
    for path in files:
        if not path.exists():continue
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_size>4096:raise ValueError('Unexpected session file: '+str(path))
        text=path.read_text()
        if path.name=='orbit-session':
            lines=[line.strip() for line in text.splitlines() if line.strip() and not line.startswith('#')]
            if len(lines)!=1 or shlex.split(lines[0]) not in (['exec',str(ROOT/'run-wayland-session.sh'),'$@'],['exec',str(ROOT/'run-wayland-session.sh')]):raise ValueError('Wrapper does not match this project')
        else:
            parser=configparser.ConfigParser(interpolation=None);parser.read_string(text)
            if parser['Desktop Entry'].get('Exec')!='/usr/local/bin/orbit-session':raise ValueError('Session entry is not owned by this Orbit launcher')
        rows.append(dict(path=str(path),mode=info.st_mode&0o777,content=text))
    return rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args();rows=inspect()
    if args.apply:
        if os.geteuid()!=0:raise PermissionError('Administrator access is needed to unregister the old session')
        # Revalidate immediately before unlinking. No packages/services/processes.
        for row in rows:
            path=Path(row['path'])
            if path.is_symlink() or path.read_text()!=row['content']:raise ValueError('Registration changed during removal')
            path.unlink()
        print(json.dumps({'removed':[row['path'] for row in rows],'native_session_preserved':True,'mint_sessions_preserved':True}))
    else:print(json.dumps(rows,indent=2))
if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError) as error:print(str(error),file=sys.stderr);sys.exit(1)

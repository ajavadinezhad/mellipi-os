#!/usr/bin/env python3
"""Run a QA command in Orbit's existing physical session, using only session-routing variables."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():continue
    try:
        if str(ROOT/'native_app.py').encode() not in (proc/'cmdline').read_bytes():continue
        entries=dict(item.split(b'=',1) for item in (proc/'environ').read_bytes().split(b'\0') if b'=' in item)
        if entries.get(b'ORBIT_QT')!=b'5' or b'SWAYSOCK' not in entries or entries.get(b'ORBIT_NESTED'):continue
        env=os.environ.copy()
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
            if key.encode() in entries:env[key]=entries[key.encode()].decode()
        os.execvpe(sys.argv[1],sys.argv[1:],env)
    except (FileNotFoundError,PermissionError,ProcessLookupError):continue
sys.exit('No running Orbit Wayland session found')

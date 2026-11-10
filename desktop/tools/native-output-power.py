#!/usr/bin/env python3
"""Typed native DPMS entry for swayidle; never contacts Sway."""
import os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from native_compositor import NativeCompositor

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('on','off'):raise ValueError('Choose on or off')
    path=os.environ.get('ORBIT_NATIVE_CONTROL')
    if not path:raise ValueError('Native control socket is unavailable')
    client=NativeCompositor(path);deadline=time.monotonic()+3
    while True:
        try:client.request('output_power',on=sys.argv[1]=='on');return 0
        except RuntimeError as error:
            if 'pageflip pending' not in str(error).lower() or time.monotonic()>=deadline:raise
            time.sleep(.025)
if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError) as error:print('Native display power: '+str(error),file=sys.stderr);sys.exit(1)

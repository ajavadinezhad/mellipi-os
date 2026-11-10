#!/usr/bin/env python3
"""Typed native DPMS entry for swayidle; never contacts Sway."""
import os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from native_compositor import NativeCompositor

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('on','off','resume'):raise ValueError('Choose on, off or resume')
    path=os.environ.get('ORBIT_NATIVE_CONTROL')
    if not path:raise ValueError('Native control socket is unavailable')
    recover=sys.argv[1]=='resume';deadline=time.monotonic()+(8 if recover else 3)
    while True:
        try:
            client=NativeCompositor(path)
            if recover:client.request('output_resume')
            else:client.request('output_power',on=sys.argv[1]=='on')
            return 0
        except (RuntimeError,OSError) as error:
            retry=('pageflip pending','seat is inactive','device inactive','resource busy','permission denied','temporarily unavailable','interrupted system call') if recover else ('pageflip pending',)
            transient=isinstance(error,OSError) and recover or any(text in str(error).lower() for text in retry)
            if not transient or time.monotonic()>=deadline:raise
            time.sleep(.1 if recover else .025)
if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError) as error:print('Native display power: '+str(error),file=sys.stderr);sys.exit(1)

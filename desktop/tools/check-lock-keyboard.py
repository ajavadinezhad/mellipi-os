#!/usr/bin/env python3
"""Exercise the locker-owned keyboard without a display or password backend."""
import argparse,os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run_checks(directory,environment=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ if environment is None else environment)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','cairo'],env=env,text=True))
    binary=directory/'keyboard-fixture'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'native'),str(ROOT/'native/lock-keyboard-harness.c'),'-o',str(binary),*flags],env=env,check=True)
    subprocess.run([str(binary),str(directory)],env=env,check=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path);a=p.parse_args()
    if a.output_dir:run_checks(a.output_dir)
    else:
        with tempfile.TemporaryDirectory(prefix='mellipi-lock-keyboard-') as temp:run_checks(temp)

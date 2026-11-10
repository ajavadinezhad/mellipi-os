#!/usr/bin/env python3
"""Compile/exercise only the lock presentation; no lock, input or PAM client."""
import argparse,os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run_checks(directory,environment=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ if environment is None else environment)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','cairo'],env=env,text=True))
    binary=directory/'textbox-render-fixture'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'native'),str(ROOT/'native/lock-textbox-harness.c'),'-o',str(binary),*flags],env=env,check=True)
    subprocess.run([str(binary),str(directory)],env=env,check=True)
    return directory
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path);args=parser.parse_args()
    if args.output_dir:run_checks(args.output_dir)
    else:
        with tempfile.TemporaryDirectory(prefix='orbit-lock-render-check-') as temp:run_checks(temp)

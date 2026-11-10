#!/usr/bin/env python3
"""Compile/read-only lock metadata fixtures; no locker, Wayland, input or PAM."""
import argparse,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run_checks(directory,environment=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ if environment is None else environment)
    binary=directory/'lock-status-fixture'
    subprocess.run(['cc','-std=c11','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror','-I'+str(ROOT/'native'),str(ROOT/'native/lock-status-harness.c'),'-o',str(binary)],env=env,check=True)
    with tempfile.TemporaryDirectory(prefix='power-supplies-',dir=directory) as supplies:
        subprocess.run([str(binary),supplies],env=env,check=True)
    return directory
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path);args=parser.parse_args()
    if args.output_dir:run_checks(args.output_dir)
    else:
        with tempfile.TemporaryDirectory(prefix='abstract-lock-status-check-') as temp:run_checks(temp)

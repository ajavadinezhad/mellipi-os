#!/usr/bin/env python3
"""Explicit control of a separately running experimental compositor."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from native_compositor import NativeCompositor
parser=argparse.ArgumentParser();parser.add_argument('--socket',required=True)
parser.add_argument('command',choices=('status','windows','workspace','move','maximize','restore','close','quit'))
parser.add_argument('values',nargs='*',type=int);args=parser.parse_args();client=NativeCompositor(args.socket)
if args.command=='workspace' and len(args.values)==1:result=client.switch_workspace(args.values[0])
elif args.command=='move' and len(args.values)==2:result=client.move(*args.values)
elif args.command in ('maximize','restore','close') and len(args.values)==1:result=client.request('maximize' if args.command=='restore' else args.command,id=args.values[0],**({'restore':True} if args.command=='restore' else {}))
elif args.command in ('status','windows','quit') and not args.values:result=client.request(args.command)
else:parser.error('Wrong number of values')
print(json.dumps(result,indent=2))

#!/usr/bin/env python3
"""One pending display transaction; stdin EOF/timeout restores the old mode.

No Qt, polling loop, credentials or permanent daemon. This process owns both
apply and rollback so shell death cannot race a parent-side apply command.
"""
import json,select,sys,time,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from display_config import catalog,command,persist,persist_native,validated
from sway_events import request as sway_request

def request(kind,payload=''):
    if os.environ.get('ORBIT_NATIVE_CONTROL'):
        from native_compositor import NativeCompositor
        client=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL'])
        if kind==3:return client.snapshot()['outputs']
        raise RuntimeError('Native display operations require typed configuration')
    return sway_request(kind,payload)

def apply(row):
    if not os.environ.get('ORBIT_NATIVE_CONTROL'):return request(0,command(row))
    from native_compositor import NativeCompositor
    client=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']);deadline=time.monotonic()+3
    while True:
        try:client.request('output_configure',settings={key:row[key] for key in ('name','mode','scale','transform','x','y')});return [{'success':True}]
        except RuntimeError as error:
            if 'pageflip pending' not in str(error).lower() or time.monotonic()>=deadline:raise
            time.sleep(.025) # bounded transaction retry; no persistent monitor loop


def emit(value):
    try:print(json.dumps(value),flush=True)
    except BrokenPipeError:pass

def run():
    applied=False;old=None;token=None;native=None;persisted=False
    try:
        raw=sys.stdin.buffer.readline(65537)
        if len(raw)>65536:raise ValueError('Display transaction is too large')
        job=json.loads(raw);rows=catalog(request(3));new=job['settings']
        new=validated(rows,**new);old=next(r for r in rows if r['name']==new['name'])
        command(old) # Refuse an apply if its exact original state cannot be restored.
        if os.environ.get('ORBIT_NATIVE_CONTROL'):
            from native_compositor import NativeCompositor
            native=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL'])
            token=native.request('output_checkpoint',name=new['name'],seconds=max(1,min(30,float(job.get('seconds',15)))))['token']
        applied=True
        reply=apply(new)
        if not reply or not all(r.get('success') for r in reply):raise RuntimeError('Display rejected these settings')
        seconds=max(1,min(30,float(job.get('seconds',15))));deadline=time.monotonic()+seconds
        emit({'ok':True,'pending':True,'deadline':deadline})
        ready=select.select([sys.stdin],[],[],max(0,deadline-time.monotonic()))[0]
        decision=sys.stdin.buffer.readline(16).strip() if ready else b''
        if decision==b'KEEP':
            current=next((r for r in catalog(request(3)) if r['name']==new['name']),None)
            if current is None:raise RuntimeError('Display disconnected before confirmation')
            if any(current[key]!=new[key] for key in ('mode','transform','x','y')) or abs(current['scale']-new['scale'])>.001:
                raise RuntimeError('Display settings changed or were rejected before confirmation')
            if native:
                native.request('output_commit',token=token)
                token=None
            (persist_native if native else persist)(job['config_path'],new);persisted=True
            applied=False;emit({'ok':True,'kept':True});return
    except Exception as error:
        emit({'ok':False,'error':str(error)[:240]})
    finally:
        if applied and old:
            try:
                if native and token:
                    deadline=time.monotonic()+3
                    while True:
                        try:native.request('output_rollback',token=token);break
                        except RuntimeError as error:
                            if 'pageflip pending' not in str(error).lower() or time.monotonic()>=deadline:raise
                            time.sleep(.025)
                elif any(r['name']==old['name'] for r in catalog(request(3))):
                    reply=apply(old)
                    if not all(r.get('success') for r in reply):raise RuntimeError('Display could not restore its previous mode')
                if persisted:(persist_native if native else persist)(job['config_path'],old)
                emit({'ok':True,'kept':False})
            except Exception as error:emit({'ok':False,'error':'Restore failed: '+str(error)[:180]})

if __name__=='__main__':run()

#!/usr/bin/env python3
"""Measure only the native shell process; no inference engine or desktop compositor."""
import argparse, json, os, signal, subprocess, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(pid):
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    ticks=int(fields[11])+int(fields[12])
    info={}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if ':' in line:
            k,v=line.split(':',1); info[k]=v.strip().split()[0] if v.strip() else ''
    pss=None
    try:
        for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
            if line.startswith('Pss:'): pss=int(line.split()[1])/1024
    except PermissionError: pass
    return dict(ticks=ticks,rss_mib=int(info['VmRSS'])/1024,pss_mib=pss,threads=int(info['Threads']),switches=int(info['voluntary_ctxt_switches'])+int(info['nonvoluntary_ctxt_switches']))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--seconds',type=int,default=10); parser.add_argument('--profile',default='baseline'); parser.add_argument('--output',required=True); args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        env=os.environ.copy(); settings=Path(tmp)/'settings.json'
        settings.write_text(json.dumps({'compact':True,'accent':'#a9d9c3','profile':args.profile if args.profile!='baseline' else 'balanced'}))
        env['ORBIT_SETTINGS_FILE']=str(settings)
        with open(ROOT/'data/benchmark.log','w') as log:
            parent=subprocess.Popen([str(ROOT/'run-native.sh'),'--keep-panels'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            try:
                child=None
                for _ in range(100):
                    if parent.poll() is not None: raise RuntimeError('Shell failed to start: '+(ROOT/'data/benchmark.log').read_text())
                    children=Path(f'/proc/{parent.pid}/task/{parent.pid}/children').read_text().split()
                    for ident in children:
                        if 'native_app.py' in Path(f'/proc/{ident}/cmdline').read_text(): child=int(ident)
                    if child and 'native shell ready' in (ROOT/'data/benchmark.log').read_text(): break
                    time.sleep(.3)
                if not child: raise RuntimeError('No native shell process found')
                time.sleep(3)
                before=read(child); start=time.monotonic(); samples=[]; backend_samples=[]
                backend_pids=[int(i) for i in Path(f'/proc/{child}/task/{child}/children').read_text().split() if 'orbit-core' in Path(f'/proc/{i}/cmdline').read_text()]
                for _ in range(args.seconds):
                    time.sleep(1); samples.append(read(child))
                    backend_samples.append([read(pid) for pid in backend_pids])
                elapsed=time.monotonic()-start; after=samples[-1]
                result={'profile':args.profile,'duration_s':round(elapsed,2),'idle_cpu_percent_one_core':round(100*(after['ticks']-before['ticks'])/os.sysconf('SC_CLK_TCK')/elapsed,3),'rss_mib':round(sum(s['rss_mib'] for s in samples)/len(samples),1),'pss_mib':round(sum(s['pss_mib'] for s in samples)/len(samples),1) if samples[0]['pss_mib'] is not None else None,'context_switches_per_second':round((after['switches']-before['switches'])/elapsed,2),'threads':after['threads'],'scope':'native shell process only, idle on current display; excludes compositor, child apps and AI inference'}
                result['backend_rss_mib']=round(sum(sum(p['rss_mib'] for p in sample) for sample in backend_samples)/len(backend_samples),1)
                result['native_plus_core_rss_mib']=round(result['rss_mib']+result['backend_rss_mib'],1)
                result['supervisor_rss_mib']=round(read(parent.pid)['rss_mib'],1)
                result['graphics_backend']=env.get('QT_QUICK_BACKEND','software (economy default)' if args.profile=='economy' else 'Qt default')
                Path(args.output).write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
            finally:
                parent.send_signal(signal.SIGTERM)
                try: parent.wait(timeout=10)
                except subprocess.TimeoutExpired: os.killpg(parent.pid,signal.SIGKILL)
if __name__=='__main__': main()

#!/usr/bin/env python3
"""Read-only hardware observations, deliberately separate from acceptance tests.

Never requests suspend, reboot, output changes, brightness writes or a seat.
Device serial numbers, EDID blobs, account names and full process environments
are not collected. A successful probe cannot certify a hardware workflow.
"""
import argparse,json,os,platform,re,shutil,stat,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

ACCEPTANCE={
 'suspend_resume':{'status':'not_tested','required':'Save work; explicitly authorize a physical suspend/resume test. Verify lock, display, input, audio and network after wake.'},
 'mixed_monitor_hotplug':{'status':'not_tested','required':'Connect two physical displays with different scale/refresh modes. Test unplug/reconnect, fullscreen, focus, window recovery and rollback.'},
 'gpu_driver_matrix':{'status':'not_tested','required':'Perform native login and workloads on each supported Intel, AMD, NVIDIA and hybrid-GPU configuration; record driver and kernel versions.'},
 'headset_microphone':{'status':'not_tested','required':'Plug in the intended microphone, select its profile/source, record and play back a sample, unplug/reconnect and test mute/media keys.'},
 'ddc_brightness':{'status':'not_tested','required':'Use a supported external monitor; change brightness, confirm it physically, reconnect and verify safe recovery.'},
 'touchscreen_unlock':{'status':'not_tested','required':'Test actual touch events and the trusted lock keyboard on physical hardware; protocol availability is insufficient.'},
 'install_recovery':{'status':'not_tested','required':'Use an owned VM or a backed-up test disk for install, password login, reboot, update, exact-version package recovery and settings restore.'},
}

def read_text(path,limit=4096):
    try:
        with Path(path).open('rb') as f:return f.read(limit).decode('utf-8',errors='replace').strip()
    except OSError:return ''

def drm_observations(sysroot=Path('/sys')):
    base=Path(sysroot)/'class/drm';cards=[];connectors=[]
    for path in sorted(base.glob('card*')):
        if re.fullmatch('card[0-9]+',path.name):
            driver=path/'device/driver'
            cards.append({'card':path.name,'driver':driver.resolve().name if driver.exists() else '',
                          'vendor':read_text(path/'device/vendor',32),'device':read_text(path/'device/device',32)})
        elif re.fullmatch('card[0-9]+-[A-Za-z0-9-]+',path.name):
            status=read_text(path/'status',32)
            if status not in ('connected','disconnected','unknown'):status='unknown'
            modes=[m for m in read_text(path/'modes').splitlines() if re.fullmatch(r'[0-9]{1,5}x[0-9]{1,5}',m)][:64]
            connectors.append({'connector':path.name,'status':status,'modes':modes,'enabled':read_text(path/'enabled',32)})
    return {'status':'observed' if cards or connectors else 'unavailable','cards':cards,'connectors':connectors,'connected_count':sum(r['status']=='connected' for r in connectors),'physical_acceptance':False}

def query(command,environment,runner=subprocess.run):
    """Commands here are fixed read-only queries; no shell, caller options or stdin."""
    try:
        r=runner(command,env=environment,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=4)
        return {'available':r.returncode==0,'output':r.stdout[:262144] if r.returncode==0 else ''}
    except (OSError,subprocess.TimeoutExpired):return {'available':False,'output':''}

def audio_observations(environment,runner=subprocess.run):
    result=query(['pactl','--format=json','list','sources'],environment,runner)
    try:
        rows=json.loads(result['output']) if result['available'] else []
        if not isinstance(rows,list):raise ValueError()
        monitors=sum(isinstance(r,dict) and (r.get('monitor_of_sink') not in (None,'',4294967295) or str(r.get('name','')).endswith('.monitor')) for r in rows)
        return {'status':'observed' if result['available'] else 'unavailable','source_count':len(rows),'monitor_source_count':monitors,'microphone_source_count':len(rows)-monitors,'physical_recording_tested':False}
    except (ValueError,TypeError):return {'status':'unavailable','physical_recording_tested':False}

def native_observations(environment):
    address=environment.get('ORBIT_NATIVE_CONTROL')
    if not address:return {'status':'unavailable','reason':'No native session control socket supplied.'}
    try:
        from native_compositor import NativeCompositor
        client=NativeCompositor(address);result=client.status();outputs=client.snapshot().get('outputs',[])
        safe=[]
        for row in outputs[:16]:
            if not isinstance(row,dict):continue
            safe.append({k:row[k] for k in ('name','current_mode','rect','scale','transform') if k in row})
        return {'status':'observed','capabilities':{k:v for k,v in result.get('capabilities',{}).items() if type(v) in (bool,int)},'outputs':safe,'physical_acceptance':False}
    except (OSError,ValueError,RuntimeError,ImportError):return {'status':'unavailable','reason':'Native control probe unavailable; no settings changed.'}

def collect(environment=None,sysroot=Path('/sys'),runner=subprocess.run,native_probe=native_observations):
    environment=dict(os.environ if environment is None else environment)
    suspend=query(['busctl','--system','call','org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager','CanSuspend'],environment,runner)
    capability=suspend['output'].strip()
    if capability not in ('s "yes"','s "no"','s "challenge"','s "na"'):capability='unknown'
    return {'format':'mellipi-hardware-readiness','version':1,'created':int(time.time()),'read_only':True,'kernel':platform.release(),
            'architecture':platform.machine(),'observations':{'drm':drm_observations(sysroot),'native':native_probe(environment),
            'audio':audio_observations(environment,runner),'suspend_capability':capability,'ddcutil_installed':bool(shutil.which('ddcutil'))},
            'acceptance':ACCEPTANCE,'all_hardware_certified':False,'changed_system_settings':False,'suspended_or_restarted_host':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,help='Create a new private JSON report; existing files are never overwritten');args=p.parse_args();report=collect();encoded=json.dumps(report,indent=2)+'\n'
    if args.output:
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:f.write(encoded)
        print(json.dumps({'report':str(args.output),'read_only':True,'hardware_certified':False}))
    else:print(encoded,end='')

if __name__=='__main__':main()

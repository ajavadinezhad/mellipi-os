#!/usr/bin/env python3
"""Measure the isolated Wayland session tree; never reads user app content."""
import json,os,time,subprocess,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def proc(pid):
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    rss=int(Path(f'/proc/{pid}/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/1048576
    pss=None
    try:
        for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
            if line.startswith('Pss:'):pss=int(line.split()[1])/1024
    except (OSError,PermissionError):pass
    return dict(pid=pid,parent=int(fields[1]),ticks=int(fields[11])+int(fields[12]),rss=rss,pss=pss,name=Path(f'/proc/{pid}/comm').read_text().strip())
def all_procs():
    result={}
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            try:
                fields=(path/'stat').read_text().rsplit(')',1)[1].split();result[int(path.name)]={'parent':int(fields[1])}
            except (OSError,ValueError,IndexError):pass
    return result
native=None
for path in Path('/proc').iterdir():
    if not path.name.isdigit():continue
    try:
        if str(ROOT/'native_app.py').encode() in (path/'cmdline').read_bytes():
            env=dict(part.split(b'=',1) for part in (path/'environ').read_bytes().split(b'\0') if b'=' in part)
            if env.get(b'ORBIT_QT')==b'5' and env.get(b'ORBIT_NESTED')==b'1' and b'SWAYSOCK' in env and (not os.environ.get('ORBIT_MEASURE_SETTINGS_FILE') or env.get(b'ORBIT_SETTINGS_FILE')==os.environ['ORBIT_MEASURE_SETTINGS_FILE'].encode()):native=int(path.name);bus_address=env[b'DBUS_SESSION_BUS_ADDRESS'];break
    except OSError:pass
if not native:raise SystemExit('No isolated Wayland Orbit instance')
response=subprocess.check_output(['gdbus','call','--address',bus_address.decode(),'--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.GetConnectionUnixProcessID','org.freedesktop.DBus'],text=True)
bus_pid=int(re.search(r'uint32 (\d+)',response).group(1))
def snapshot():
    result={}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            values=dict(item.split(b'=',1) for item in (path/'environ').read_bytes().split(b'\0') if b'=' in item)
            if int(path.name)==bus_pid or values.get(b'DBUS_SESSION_BUS_ADDRESS')==bus_address:
                result[int(path.name)]=proc(int(path.name))
        except (OSError,ValueError,IndexError):pass
    return result
before=snapshot();start=time.monotonic();samples=[]
for _ in range(15):time.sleep(1);samples.append(snapshot())
after=samples[-1];seconds=time.monotonic()-start
cpu=sum(p['ticks']-before[pid]['ticks'] for pid,p in after.items() if pid in before)/os.sysconf('SC_CLK_TCK')/seconds*100
result=dict(duration_s=round(seconds,2),idle_cpu_percent_one_core=round(cpu,2),session_rss_mib=round(sum(sum(p['rss'] for p in s.values()) for s in samples)/len(samples),1),session_pss_mib=round(sum(sum(p['pss'] or 0 for p in s.values()) for s in samples)/len(samples),1),processes=[dict(name=p['name'],rss_mib=round(p['rss'],1)) for p in after.values()],scope='Processes on the private nested Wayland session bus, including compositor, shell, Rust core, session bus and activated session services. Excludes outer X server, applications outside this session, and AI inference. Idle software rendering on this display; not target-hardware certification.')
(ROOT/'wayland-metrics.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

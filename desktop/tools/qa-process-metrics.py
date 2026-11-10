#!/usr/bin/env python3
"""Process metrics shared by isolated desktop QA fixtures.

Kept separate from retired Fold/sharing UI tests so active QA does not import
obsolete UI workflows. Only a supplied private session bus is sampled.
"""
import os,re,subprocess,time
from pathlib import Path

def idle_sample(native,seconds=8):
    """Measure only processes on this private bus, plus that bus's daemon."""
    address=native['DBUS_SESSION_BUS_ADDRESS']
    response=subprocess.check_output(['gdbus','call','--address',address,'--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.GetConnectionUnixProcessID','org.freedesktop.DBus'],text=True,env=native,timeout=3)
    bus_pid=int(re.search(r'uint32 (\d+)',response).group(1))
    def snapshot():
        values={}
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():continue
            try:
                entries=dict(part.split(b'=',1) for part in (process/'environ').read_bytes().split(b'\0') if b'=' in part)
                pid=int(process.name)
                if pid!=bus_pid and entries.get(b'DBUS_SESSION_BUS_ADDRESS')!=address.encode():continue
                fields=(process/'stat').read_text().rsplit(')',1)[1].split();pss=0
                for line in (process/'smaps_rollup').read_text().splitlines():
                    if line.startswith('Pss:'):pss=int(line.split()[1])/1024;break
                rss=int((process/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/1048576
                values[pid]=dict(ticks=int(fields[11])+int(fields[12]),rss=rss,pss=pss,name=(process/'comm').read_text().strip())
            except (OSError,ValueError,IndexError):pass
        return values
    before=snapshot();began=time.monotonic();samples=[]
    for _ in range(seconds):time.sleep(1);samples.append(snapshot())
    duration=time.monotonic()-began;after=samples[-1]
    cpu=sum(row['ticks']-before[pid]['ticks'] for pid,row in after.items() if pid in before)/os.sysconf('SC_CLK_TCK')/duration*100
    return dict(duration_seconds=round(duration,2),cpu_percent_one_core=round(cpu,2),pss_mib=round(sum(sum(row['pss'] for row in sample.values()) for sample in samples)/len(samples),1),summed_rss_mib=round(sum(sum(row['rss'] for row in sample.values()) for sample in samples)/len(samples),1),processes=[row['name'] for row in after.values()])

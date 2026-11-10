#!/usr/bin/env python3
"""Read only an explicitly disposable Orbit accessibility bus; never host apps."""
import json,os,sys,time
if os.environ.get('ORBIT_NESTED')!='1' or os.environ.get('ORBIT_QA')!='1' or not os.environ.get('ORBIT_NATIVE_CONTROL') or not os.environ.get('ORBIT_NATIVE_NESTED_BUS'):
    raise SystemExit('Requires the owned native-shell QA bus')
import pyatspi
end=time.monotonic()+10
while time.monotonic()<end:
    try:
        desktop=pyatspi.Registry.getDesktop(0)
        for app in desktop:
            if app.name!='orbit-shell':continue
            count=0;editable=False;stack=[app]
            while stack and count<1200:
                item=stack.pop();count+=1
                if item.getRoleName() in ('entry','text','password text'):
                    try:
                        if item.getState().contains(pyatspi.STATE_EDITABLE):editable=True
                    except Exception:pass
                try:stack.extend(child for child in item if child is not None)
                except Exception:pass
            if editable:
                print(json.dumps(dict(application='orbit-shell',nodes=count,editable_control=True,physical_desktop_inspected=False)));sys.exit(0)
    except Exception:pass
    time.sleep(.1)
raise SystemExit('No accessible editable launcher control on private bus')

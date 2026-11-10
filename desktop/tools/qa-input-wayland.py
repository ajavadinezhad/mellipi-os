#!/usr/bin/env python3
"""Actual virtual-device outside-click, Quick-tab, tooltip and menu QA in a private desktop."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
spec=importlib.util.spec_from_file_location('qa',ROOT/'tools/qa-screenshots-wayland.py');qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)
import sway_events
session=fixture=None;routed=False
with tempfile.TemporaryDirectory(prefix='orbit-focus-qa-') as tmp,open('/tmp/orbit-focus-qa.log','w') as log:
 settings=Path(tmp)/'settings.json';settings.write_text(json.dumps({'profile':'economy','reducedMotion':True}));env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=tmp+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=tmp+'/config')
 try:
  session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  pid,native=qa.wait(lambda:qa.native_process(settings),30)
  for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
   if key in native:os.environ[key]=native[key]
  routed=True;qa.wait(lambda:qa.control('status'))
  native['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell'
  fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=native,stdout=log,stderr=log)
  node=qa.wait(lambda:(qa.fixture_windows(sway_events.request(4)) or [None])[0]);r=node['rect']
  def click(x,y):
   sway_events.command(f'seat seat0 cursor set {x} {y}');sway_events.command('seat seat0 cursor press button1');sway_events.command('seat seat0 cursor release button1');time.sleep(.2)
  spec2=importlib.util.spec_from_file_location('pointer',str(ROOT/'tools/qa_wayland_input.py'));pointer=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(pointer)
  virtual=pointer.VirtualPointer(native)
  sway_events.command(f'[con_id={node["id"]}] move absolute position 20 px 250 px')
  for page in ('launcher','quick','music','settings','launcher'):
   qa.control(page);qa.wait(lambda:qa.control('status')['panel']==page);time.sleep(.3)
   virtual.click(100,350)
   qa.wait(lambda:qa.control('status')['panel']=='',3)
   print('PASS actual virtual pointer outside click',page,flush=True)
  qa.control('quick');time.sleep(.4)
  for x in (1090,1194,986,1090):
   virtual.click(x,114);time.sleep(.3);state=qa.control('status');assert state['panel']=='quick',state['panel'];assert not state['qml_errors'],state['qml_errors']
   print('PASS actual Quick tab click',x,state['panel_mask'],flush=True)
  qa.control('launcher');time.sleep(.4)
  virtual.click(320,270,button=273);qa.wait(lambda:qa.control('status')['context_open'],3)
  g=qa.control('qa-context-geometry');assert abs(g['x']-320)<3 and abs(g['y']-270)<3,g
  print('PASS actual launcher right-click',g,flush=True);qa.control('qa-close-menu');time.sleep(.3)
  virtual.move(760,211);time.sleep(.7);tip=qa.control('status')['tooltip'];assert tip and tip['x']>600 and tip['y']>150,tip
  print('PASS actual panel tooltip',tip,flush=True)
  virtual.close()
  qa.control('quit');session.wait(timeout=12);assert session.returncode==0
 finally:
  if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=5)
  if session and session.poll() is None and routed:
   try:sway_events.command('exit')
   except Exception:pass
  if session and session.poll() is None:
   try:session.wait(timeout=5)
   except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)

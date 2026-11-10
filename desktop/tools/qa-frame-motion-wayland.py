"""Private titlebar-size and actual pointer-motion QA; never touches the user session."""
import importlib.util,json,os,subprocess,sys,tempfile,time,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
qa=load('qa',ROOT/'tools/qa-screenshots-wayland.py');inputs=load('inputs',ROOT/'tools/qa_wayland_input.py')
import sway_events
from window_actions import find_window
from PySide6.QtGui import QImage
session=fixture=None;native=None
with tempfile.TemporaryDirectory(prefix='orbit-motion-') as temp,open('/tmp/orbit-motion.log','w') as log:
 settings=Path(temp)/'settings.json';settings.write_text(json.dumps({'profile':'economy','reducedMotion':True,'desktopIcons':False,'frameStyle':'normal'}));env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temp+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=temp+'/config')
 try:
  session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  pid,native=qa.wait(lambda:qa.native_process(settings),30)
  for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
   if key in native:os.environ[key]=native[key]
  qa.wait(lambda:qa.control('status'))
  child=native.copy();child['QT_QPA_PLATFORM']=sys.argv[1] if len(sys.argv)>1 else 'wayland';child.pop('QT_WAYLAND_SHELL_INTEGRATION',None)
  fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=child,stdout=log,stderr=log)
  ident=int(qa.wait(lambda:next((n['id'] for n in sway_events.parse_tree(sway_events.request(4)) if n['title']=='Orbit disposable screenshot fixture'),None),10))
  sway_events.command(f'[con_id={ident}] border normal 2; [con_id={ident}] floating enable; [con_id={ident}] resize set width 500 px height 260 px; [con_id={ident}] move absolute position 150 px 150 px')
  qa.wait(lambda:qa.control('status')['frame_controls'].get('id')==str(ident),10)
  for size in (6,8,10,16):
   sway_events.command('font pango:Sans '+str(size));time.sleep(.3)
   n=find_window(sway_events.request(4),ident)[0];f=qa.control('status')['frame_controls']
   assert f['height']==min(32,n['deco_rect']['height']),f
   print('FONT',size,'RECT',n['rect'],'DECO',n['deco_rect'],'OUTER',n['_outer_rect'],'FRAME',f,flush=True)
  sway_events.command('font pango:Sans 10');time.sleep(.3)
  pointer=inputs.VirtualPointer(native);n=find_window(sway_events.request(4),ident)[0];f=qa.control('status')['frame_controls'];x=n['_outer_rect']['x']+60;y=f['y']+f['height']//2
  pointer.move(x,y);stamp=int(time.monotonic()*1000)&0xffffffff;pointer.send(5,2,struct.pack('=III',stamp,272,1));pointer.send(5,4);pointer.roundtrip()
  samples=[]
  for i in range(45):
   pointer.move(x+i*4,y+i*2);time.sleep(1/60)
   n=find_window(sway_events.request(4),ident)[0];f=qa.control('status')['frame_controls'];expected=n['_outer_rect']['x']+n['_outer_rect']['width']-86
   samples.append(abs(f['x']-expected))
   if i in (0,10,25,44):
    image=QImage.fromData(subprocess.check_output(['grim','-t','png','-'],env=native,stderr=log));image.save('/tmp/orbit-motion-'+str(i)+'.png')
  pointer.send(5,2,struct.pack('=III',stamp+1,272,0));pointer.send(5,4);pointer.roundtrip();pointer.close()
  assert max(samples[6:])<=24,samples
  print('DRAG offsets',samples,'MAX',max(samples),'POST-WARMUP-MAX',max(samples[6:]),flush=True)
  qa.control('quit');session.wait(timeout=12)
 finally:
  if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
  if session and session.poll() is None and native:
   try:sway_events.command('exit')
   except Exception:pass
  if session and session.poll() is None:session.terminate();session.wait(timeout=5)

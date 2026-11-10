import os,sys,json,time,tempfile,subprocess,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def mod(name,file):
 s=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
qa=mod('qa','qa-screenshots-wayland.py');inputs=mod('inputs','qa_wayland_input.py')
with tempfile.TemporaryDirectory(prefix='orbit-visual-') as temp,open('/tmp/orbit-visual.log','w') as log:
 d=Path(temp);settings=d/'settings.json';(d/'config').mkdir();(d/'Desktop').mkdir();(d/'Desktop'/'fixture.txt').write_text('Private icon')
 (d/'config'/'user-dirs.dirs').write_text('XDG_DESKTOP_DIR="'+str(d/'Desktop')+'"\n')
 settings.write_text(json.dumps(dict(profile='balanced',shellLayout='fold',desktopIcons=True,workspaceMotion=True,reducedMotion=False)))
 env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(d/'data'),ORBIT_QA='1',PULSE_SERVER='unix:'+str(d/'noaudio'),XDG_CONFIG_HOME=str(d/'config'),ORBIT_FOLD_DIR=str(d),ORBIT_FOLD_STATE=str(d/'fold.json'))
 session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True);pointer=fixture=None
 try:
  pid,native=qa.wait(lambda:qa.native_process(settings),30);assert native['ORBIT_NESTED']=='1'
  for k in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
   if k in native:os.environ[k]=native[k]
  qa.wait(lambda:qa.control('status'));pointer=inputs.VirtualPointer(native)
  import sway_events
  import struct
  sway_events.command('workspace number 1');time.sleep(.3)
  checks=[]
  for label,key,target in [('Left wraps',105,4),('Right wraps',106,1),('Down advances',108,2),('Up returns',103,1)]:
   generation=qa.control('status')['transition']['generation'];stamp=int(time.monotonic()*1000)&0xffffffff
   pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',12,0,0,0))
   pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,key,1));pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,key,0))
   pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',0,0,0,0));pointer.roundtrip()
   qa.wait(lambda:next(w['num'] for w in sway_events.request(1) if w.get('focused'))==target,5)
   qa.wait(lambda:qa.control('status')['transition']['generation']>generation and not qa.control('status')['transition']['visible'],5)
   assert qa.control('status')['panel']=='','shortcut opened a panel'
   assert qa.control('status')['transition']['direction']==(-1 if key in (105,103) else 1),'wrong slide direction'
   checks.append(label);print('PASS',label,flush=True)
  grid=qa.control('qa-shell-item:desktopIconsGrid');assert grid['x']>=80 and grid['y']==16,grid
  checks.append('desktop icons clear the Spine edge')
  sway_events.command('workspace number 9')
  marker=qa.wait(lambda:qa.control('qa-shell-item:spineWorkspace_8'),4)
  qa.wait(lambda:70<=qa.control('qa-shell-item:spineWorkspace_8')['y']<240,4)
  checks.append('workspace beyond four stays reachable and visible')
  sway_events.command('workspace number 1');time.sleep(.3)
  child=dict(native,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
  fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code],env=child,stdout=log,stderr=log)
  owned=qa.wait(lambda:next((w for w in sway_events.parse_tree(sway_events.request(4)) if w.get('pid')==fixture.pid),None),8)
  from window_actions import find_window
  qa.wait(lambda:find_window(sway_events.request(4),int(owned['id']))[0].get('border')=='csd',5)
  checks.append('Wayland app owns its decoration surface')
  qa.control('launcher');qa.wait(lambda:qa.control('qa-shell-item:foldAppSearch'),4)
  sort=qa.control('qa-shell-item:launcherSortOptions')
  for column,mode in ((2,'name'),(1,'recent'),(0,'frequent')):
   pointer.click(round(sort['x']+sort['width']*(column+.5)/3),round(sort['y']+sort['height']/2))
   qa.wait(lambda:qa.control('status')['launcher_sort']==mode,4)
   assert json.loads(settings.read_text())['launcherSort']==mode
  checks.append('all three app sort controls persist through real pointer input')
  rect=qa.control('qa-shell-item:foldAppSearch');pointer.click(round(rect['x']+40),round(rect['y']+rect['height']/2))
  for key in (33,23,45,20,22,19,18):
   stamp=int(time.monotonic()*1000)&0xffffffff;pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,key,1));pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,key,0))
  pointer.roundtrip();time.sleep(.2)
  stamp=int(time.monotonic()*1000)&0xffffffff;pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,28,1));pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,28,0));pointer.roundtrip()
  qa.wait(lambda:qa.control('status')['panel']=='',4)
  qa.wait(lambda:any(w['id']==owned['id'] and w['active'] for w in sway_events.parse_tree(sway_events.request(4))),4)
  checks.append('real search typing and Enter activates owned window')
  assert not qa.control('status')['qml_errors']
  print(json.dumps(dict(private=True,checks=checks,qml_errors=[])))
  fixture.terminate();fixture.wait(timeout=3);fixture=None
  pointer.close();pointer=None;qa.control('quit');session.wait(timeout=15)
 finally:
  if pointer:pointer.close()
  if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
  if session.poll() is None:session.terminate();session.wait(timeout=5)

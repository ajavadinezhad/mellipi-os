"""Private pixel checks for raising apps through maximized floating windows."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
spec=importlib.util.spec_from_file_location('qa',ROOT/'tools/qa-screenshots-wayland.py');qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)
import sway_events
spec2=importlib.util.spec_from_file_location('inputs',ROOT/'tools/qa_wayland_input.py');inputs=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(inputs)
from PySide6.QtGui import QImage
from window_actions import WindowActions,find_window
session=fixture=None;routed=False
with tempfile.TemporaryDirectory(prefix='orbit-stacking-') as temp,open('/tmp/orbit-stacking.log','w') as log:
 settings=Path(temp)/'settings.json';settings.write_text(json.dumps({'profile':'economy','reducedMotion':True,'desktopIcons':False}));env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temp+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=temp+'/config')
 try:
  session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  pid,native=qa.wait(lambda:qa.native_process(settings),30)
  for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
   if key in native:os.environ[key]=native[key]
  routed=True;qa.wait(lambda:qa.control('status'))
  child=native.copy();child['QT_QPA_PLATFORM']='wayland';child.pop('QT_WAYLAND_SHELL_INTEGRATION',None)
  fixture=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code.replace('#f0f4f5','#d32b3b')],env=child,stdout=log,stderr=log)
  first=qa.wait(lambda:(qa.fixture_windows(sway_events.request(4)) or [None])[0],10);a=first['id']
  other=subprocess.Popen(['/usr/bin/python3','-c',qa.fixture_code.replace('#f0f4f5','#123cc4')],env=child,stdout=log,stderr=log)
  b=qa.wait(lambda:next((n['id'] for n in qa.fixture_windows(sway_events.request(4)) if n['id']!=a),None),10)
  actions=WindowActions()
  def inspect(label):
   views=qa.fixture_windows(sway_events.request(4));print(label,json.dumps([dict(id=n['id'],focused=n['focused'],floating=n.get('floating'),fullscreen=n.get('fullscreen_mode'),rect=n['rect']) for n in views]),flush=True)
  sway_events.command(f'[con_id={a}] resize set width 500 px height 350 px; [con_id={a}] move absolute position 100 px 100 px')
  actions.maximize(b,True);actions.restore(a);inspect('floating focus behind maximized')
  def pixel():
   image=QImage.fromData(subprocess.check_output(['grim','-t','png','-'],env=native,stderr=log));return image.pixelColor(200,200).name()
  sway_events.command(f'[con_id={a}] floating disable; [con_id={b}] focus; [con_id={a}] focus')
  qa.wait(lambda:pixel()=='#123cc4',4);assert find_window(sway_events.request(4),a)[0]['focused']
  before=find_window(sway_events.request(4),a)[0]['_outer_rect'];print('PROVED old focus-only leaves blue maximized app above focused red tiled app',flush=True)
  actions.restore(a)
  qa.wait(lambda:pixel()=='#d32b3b',4)
  restored=find_window(sway_events.request(4),a)[0];assert restored['focused'] and restored['_floating'];assert restored['_outer_rect']==before,(before,restored['_outer_rect'])
  assert actions.is_maximized(b),'Other app lost its maximize state'
  print('PASS fixed activation raises red app, exact outer bounds preserved, other app remains maximized',flush=True)
  for i in range(6):
   actions.restore(b);qa.wait(lambda:pixel()=='#123cc4',4)
   actions.restore(a);qa.wait(lambda:pixel()=='#d32b3b',4)
  actions.minimize(a);actions.restore(b);actions.restore(a);qa.wait(lambda:pixel()=='#d32b3b',4)
  print('PASS six alternating activations plus minimize/restore all really visible',flush=True)
  sway_events.command(f'[con_id={a}] floating disable; [con_id={b}] focus')
  original=find_window(sway_events.request(4),a)[0]['_outer_rect'];actions.minimize(a);actions.restore(b);actions.restore(a)
  qa.wait(lambda:pixel()=='#d32b3b',4);restored=find_window(sway_events.request(4),a)[0]
  assert restored['_floating'] and restored['_outer_rect']==original
  print('PASS originally tiled minimized target returns visibly above maximized app with exact bounds',flush=True)
  sway_events.command(f'[con_id={a}] floating disable; [con_id={b}] focus')
  qa.wait(lambda:any(w['id']==str(b) and w['active'] for w in qa.control('qa-window-state')['windows']),4)
  qa.control('switch-next');qa.control('switch-accept')
  qa.wait(lambda:qa.control('status')['panel']=='',4);qa.wait(lambda:pixel()=='#d32b3b',4)
  assert find_window(sway_events.request(4),a)[0]['focused'];print('PASS real Bridge Alt+Tab path raises formerly tiled app',flush=True)
  sway_events.command(f'[con_id={a}] floating disable; [con_id={b}] focus')
  qa.wait(lambda:any(w['id']==str(b) and w['active'] for w in qa.control('qa-window-state')['windows']),4)
  qa.control('overview');qa.wait(lambda:qa.control('qa-fold-state')['state']['view']=='unfold',4)
  grid=qa.control('qa-fold-item:foldWindowGrid');assert grid['visible']
  pointer=inputs.VirtualPointer(native)
  pointer.click(round(grid['x']+grid['width']/6),round(grid['y']+68));pointer.close()
  qa.wait(lambda:qa.control('status')['panel']=='',4);qa.wait(lambda:pixel()=='#d32b3b',4)
  assert find_window(sway_events.request(4),a)[0]['focused'];print('PASS actual Unfold first-card pointer click raises formerly tiled app',flush=True)
  other.terminate();other.wait(timeout=3)
  qa.control('quit');session.wait(timeout=12)
 finally:
  if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=3)
  if session and session.poll() is None and routed:
   try:sway_events.command('exit')
   except Exception:pass
  if session and session.poll() is None:
   try:session.wait(timeout=5)
   except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)

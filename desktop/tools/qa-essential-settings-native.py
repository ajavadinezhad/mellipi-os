#!/usr/bin/env python3
"""Read-only essential Settings acceptance in a private nested native desktop."""
import hashlib,json,os,selectors,signal,socket,subprocess,tempfile,time,sys
from pathlib import Path
import argparse
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description="Verify essential Settings pages and a real file chooser in a private nested desktop; never mutates accounts or clock.")
parser.add_argument('--package',type=Path,required=True)
args=parser.parse_args()
package=args.package.resolve()
assert package.is_file() and not args.package.is_symlink(), 'Use a reviewed regular package'
assert subprocess.check_output(['dpkg-deb','-f',str(package),'Package'],text=True).strip()=='mellipi-shell'
BASE=Path(tempfile.mkdtemp(prefix='mellipi-essential-settings-'))
STAGE=BASE/'package';STAGE.mkdir()
subprocess.run(['dpkg-deb','-x',str(package),str(STAGE)],check=True)
INSTALLED=STAGE/'usr/lib/abstract'
OUT=BASE/'images';OUT.mkdir(mode=0o700)
(BASE/'runtime').mkdir(mode=0o700);(BASE/'home').mkdir(mode=0o700)
sys.path.insert(0,str(INSTALLED));os.environ['ORBIT_QT']='5'
from preferences import Preferences
prefs=Preferences(BASE/'config/abstract/settings.json');prefs.apply_theme('forest');prefs.update({'profile':'balanced','density':'comfortable','desktopIcons':False,'idleLockEnabled':False,'displayOffMinutes':0,'matchApps':False,'matchWindows':False,'taskbarFloating':True,'taskbarLength':'fit','panelPosition':'left','pins':['firefox.desktop','thunar.desktop']})
config=BASE/'sway.conf';config.write_text('output HEADLESS-1 mode 1440x900\nseat seat0 fallback true\ndefault_border none\nfor_window [app_id="orbit-native"] fullscreen enable\n')
def wait(check,seconds=30):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=check()
  if value:return value
  time.sleep(.05)
 raise AssertionError('Private gallery session timed out')
def stop(child):
 if child and child.poll() is None:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=3)
parent=owner=None
with (BASE/'session.log').open('w') as log:
 try:
  env={k:v for k,v in os.environ.items() if k not in ('WAYLAND_DISPLAY','DISPLAY','SWAYSOCK','DBUS_SESSION_BUS_ADDRESS','AT_SPI_BUS_ADDRESS','ORBIT_NATIVE_CONTROL','ORBIT_DATA','ORBIT_SETTINGS_FILE','ORBIT_FOLD_STATE','QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH','LD_LIBRARY_PATH')}
  env.update(HOME=str(BASE/'home'),USER='mellipi',LOGNAME='mellipi',XDG_RUNTIME_DIR=str(BASE/'runtime'),XDG_CONFIG_HOME=str(BASE/'config'),XDG_DATA_HOME=str(BASE/'data'),XDG_DATA_DIRS=str(STAGE/'usr/share')+':/usr/local/share:/usr/share',XDG_STATE_HOME=str(BASE/'state'),XDG_CACHE_HOME=str(BASE/'cache'),ORBIT_DATA=str(BASE/'data/abstract'),ORBIT_SETTINGS_FILE=str(prefs.path),ORBIT_FOLD_STATE=str(BASE/'data/abstract/fold-state.json'),ORBIT_INSTALLED_SESSION='1',ORBIT_QA='1',ORBIT_NESTED='1',WLR_BACKENDS='headless',WLR_RENDERER='pixman',WLR_LIBINPUT_NO_DEVICES='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',PULSE_SERVER='unix:'+str(BASE/'runtime/no-audio'))
  parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh;exec sway -c "$1"','mellipi-gallery',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  outer=wait(lambda:next((p.name for p in (BASE/'runtime').glob('wayland-*') if not p.name.endswith('.lock')),None))
  owner=subprocess.Popen(['/usr/bin/python3',str(INSTALLED/'session/native_session.py'),'--nested'],cwd=INSTALLED,env=dict(env,WAYLAND_DISPLAY=outer,WINIT_UNIX_BACKEND='wayland'),stdout=subprocess.PIPE,stderr=log,start_new_session=True)
  selector=selectors.DefaultSelector();selector.register(owner.stdout,selectors.EVENT_READ);buffer=b'';info=None;end=time.monotonic()+40
  while time.monotonic()<end and info is None:
   assert owner.poll() is None,'Private native owner exited'
   for key,_ in selector.select(.2):
    buffer+=os.read(key.fd,65536)
    while b'\n' in buffer:
     line,buffer=buffer.split(b'\n',1)
     try:row=json.loads(line)
     except ValueError:continue
     if row.get('ready'):info=row
  selector.close();assert info,'No private native readiness'
  display=info['wayland_display'];address=BASE/'runtime'/f'orbit-{os.getuid()}'/('control-'+hashlib.sha256(display.encode()).hexdigest()[:12])
  def control(command):
   if not address.exists():return None
   with socket.socket(socket.AF_UNIX) as connection:
    connection.settimeout(4);connection.connect(str(address));connection.sendall((command+'\n').encode());data=b''
    while True:
     part=connection.recv(65536)
     if not part:break
     data+=part
    return json.loads(data) if data else None
  state=wait(lambda:control('status'));assert not state['qml_errors'],state['qml_errors']
  capture_env=dict(env,WAYLAND_DISPLAY=display)
  def capture(name):
   time.sleep(1.3)
   state=control('status');assert not state['qml_errors'],state['qml_errors']
   if state.get('settings_window',{}).get('errors'):raise AssertionError(state['settings_window']['errors'])
   path=BASE/(name+'.png');subprocess.run(['grim','-t','png',str(path)],env=capture_env,check=True,capture_output=True,timeout=15)
   from PIL import Image
   picture=Image.open(path);assert picture.width>=1200 and picture.height>=800,(picture.width,picture.height)
   picture.save(OUT/(name+'.webp'),format='WEBP',quality=92,method=6)
   return {'name':name,'width':picture.width,'height':picture.height,'bytes':(OUT/(name+'.webp')).stat().st_size,'png':str(path)}
  control('system-settings');wait(lambda:(control('status') or {}).get('settings_window',{}).get('ready'));
  for section in (12,10,2,15,8,9,5,0,6,7,1,4,3,16):
   control('qa-system-section:'+str(section));time.sleep(.15);state=control('status');assert not state['settings_window']['errors']
  captures=[]
  for tool in ('users','datetime','recovery'):
   control('qa-essential-tool:'+tool);time.sleep(1);captures.append(capture('essentials-'+tool))
  from native_compositor import NativeCompositor
  client=NativeCompositor(info['control'])
  control('qa-essential-tool:choose-folder')
  rows=wait(lambda:(lambda windows:windows if any('folder' in row.get('title','').lower() for row in windows) else None)(client.windows()),seconds=20)
  captures.append(capture('essentials-folder-picker'))
  client.request('close',id=next(r['id'] for r in rows if 'folder' in r.get('title','').lower()));time.sleep(.3)
  first,second=captures[0],captures[1]
  result={'private_capture':True,'physical_user_windows_captured':False,'theme':'Forest','images':captures,'qml_errors':[]};(BASE/'provenance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
 finally:
  stop(owner);stop(parent)
  for name in ('gvfs','doc'):subprocess.run(['fusermount3','-uz',str(BASE/'runtime'/name)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

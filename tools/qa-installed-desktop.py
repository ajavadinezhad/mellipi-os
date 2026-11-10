#!/usr/bin/env python3
"""Smoke-test installed program files using only owned nested processes/state."""
import hashlib,json,os,selectors,signal,socket,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def wait(check,seconds=25):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=check()
  if value:return value
  time.sleep(.05)
 raise AssertionError('Installed desktop QA timed out')
def stop(child):
 if child and child.poll() is None:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=3)
def main():
 parent=owner=None
 installed=Path('/usr/lib/abstract');assert (installed/'native_app.py').is_file()
 with tempfile.TemporaryDirectory(prefix='abstract-installed-qa-',ignore_cleanup_errors=True) as directory,open('/tmp/abstract-installed-desktop.log','w') as log:
  base=Path(directory);runtime=base/'runtime';runtime.mkdir(mode=0o700)
  home=base/'home';home.mkdir(mode=0o700)
  config=base/'sway.conf';config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\n')
  env={k:v for k,v in os.environ.items() if k not in ('WAYLAND_DISPLAY','DISPLAY','SWAYSOCK','DBUS_SESSION_BUS_ADDRESS','AT_SPI_BUS_ADDRESS','ORBIT_NATIVE_CONTROL','ORBIT_DATA','ORBIT_SETTINGS_FILE','ORBIT_FOLD_STATE','QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH','LD_LIBRARY_PATH')}
  env.update(HOME=str(home),XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(base/'config'),XDG_DATA_HOME=str(base/'data'),XDG_STATE_HOME=str(base/'state'),XDG_CACHE_HOME=str(base/'cache'),ORBIT_QA='1',ORBIT_NESTED='1',WLR_BACKENDS='headless',WLR_RENDERER='pixman',WLR_LIBINPUT_NO_DEVICES='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',PULSE_SERVER='unix:'+str(runtime/'no-audio'))
  try:
   parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh;exec sway -c "$1"','abstract-installed',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
   display=wait(lambda:next((p.name for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
   owner=subprocess.Popen(['/usr/bin/abstract-session','--nested'],cwd=base,env=dict(env,WAYLAND_DISPLAY=display,WINIT_UNIX_BACKEND='wayland'),stdout=subprocess.PIPE,stderr=log,start_new_session=True)
   selector=selectors.DefaultSelector();selector.register(owner.stdout,selectors.EVENT_READ);buffer=b'';info=None;end=time.monotonic()+35
   while time.monotonic()<end and info is None:
    assert owner.poll() is None,'Installed owner exited: /tmp/abstract-installed-desktop.log'
    for key,_ in selector.select(.2):
     buffer+=os.read(key.fd,65536)
     while b'\n' in buffer:
      line,buffer=buffer.split(b'\n',1)
      try:row=json.loads(line)
      except ValueError:continue
      if row.get('ready'):info=row
   selector.close();assert info,'No installed native readiness'
   display=info['wayland_display'];assert isinstance(display,str)
   address=runtime/f'orbit-{os.getuid()}'/('control-'+hashlib.sha256(display.encode()).hexdigest()[:12])
   def control(command):
    if not address.exists():return None
    with socket.socket(socket.AF_UNIX) as connection:
     connection.settimeout(3);connection.connect(str(address));connection.sendall((command+'\n').encode());data=b''
     while True:
      part=connection.recv(65536)
      if not part:break
      data+=part
     return json.loads(data) if data else None
   state=wait(lambda:control('status'));assert not state['qml_errors'],state['qml_errors']
   control('launcher');wait(lambda:(control('status') or {}).get('panel')=='launcher')
   control('launcher');control('system-settings')
   wait(lambda:(control('status') or {}).get('settings_window',{}).get('ready'))
   # Exercise real settings pages, including recently added system integration.
   sections=(12,10,2,15,8,9,5,0,6,7,1,4,3,16)
   for section in sections:
    control('qa-system-section:'+str(section));time.sleep(.15)
    state=control('status');assert not state['settings_window']['errors'],state['settings_window']['errors']
   assert not control('status')['qml_errors']
   print(json.dumps(dict(installed_program_root=str(installed),private_state=True,launcher=True,settings=True,settings_sections=list(sections),qml_errors=[],physical_session_changed=False)))
  finally:
   stop(owner);stop(parent)
   # Owned bus activations may leave disconnected private GIO/document FUSE
   # mounts briefly after process exit. Never touch the user's runtime mounts.
   for name in ('gvfs','doc'):
    subprocess.run(['fusermount3','-uz',str(runtime/name)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   time.sleep(.2)
if __name__=='__main__':main()

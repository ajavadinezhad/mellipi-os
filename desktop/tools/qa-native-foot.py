#!/usr/bin/env python3
"""Regression for native xdg configure/focus ordering and real terminal input.

Runs a headless Sway parent and a private nested installed Mellipi session.
Requires Foot (or an extracted official package), Sway, and installed app files.
For an extracted Foot, pass its private dependency directory via --library-path.
Example:
  python3 tools/qa-native-foot.py --installed-root /tmp/stage/usr/lib/abstract \
    --foot /usr/bin/foot --report-dir /tmp/abstract-foot-report

The real Foot child must map, receive configure before keyboard focus, accept
'a' and Enter through the private parent keyboard, and remain alive 10 seconds.
All processes, homes, displays and input sockets are owned private fixtures.
"""
import argparse,hashlib,json,os,selectors,signal,socket,subprocess,tempfile,time
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
 parser=argparse.ArgumentParser(description='Private nested native Foot mapping and keyboard regression; never attaches to a physical session.')
 parser.add_argument('--installed-root',type=Path,required=True)
 parser.add_argument('--foot',type=Path,required=True)
 parser.add_argument('--library-path',default='')
 parser.add_argument('--report-dir',type=Path,required=True)
 args=parser.parse_args()
 args.report_dir.mkdir(parents=True,exist_ok=True)
 parent=owner=foot=None
 installed=args.installed_root.resolve();assert (installed/'native_app.py').is_file()
 with tempfile.TemporaryDirectory(prefix='abstract-installed-qa-',ignore_cleanup_errors=True) as directory,open(args.report_dir/'native.log','w') as log:
  base=Path(directory);runtime=base/'runtime';runtime.mkdir(mode=0o700)
  home=base/'home';home.mkdir(mode=0o700)
  config=base/'sway.conf';config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\n')
  env={k:v for k,v in os.environ.items() if k not in ('WAYLAND_DISPLAY','DISPLAY','SWAYSOCK','DBUS_SESSION_BUS_ADDRESS','AT_SPI_BUS_ADDRESS','ORBIT_NATIVE_CONTROL','ORBIT_DATA','ORBIT_SETTINGS_FILE','ORBIT_FOLD_STATE','QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH','LD_LIBRARY_PATH')}
  env.update(HOME=str(home),XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(base/'config'),XDG_DATA_HOME=str(base/'data'),XDG_STATE_HOME=str(base/'state'),XDG_CACHE_HOME=str(base/'cache'),ORBIT_QA='1',ORBIT_NESTED='1',WLR_BACKENDS='headless',WLR_RENDERER='pixman',WLR_LIBINPUT_NO_DEVICES='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',PULSE_SERVER='unix:'+str(runtime/'no-audio'))
  try:
   parent=subprocess.Popen(['bash','-c','source tools/wayland-env.sh;exec sway -c "$1"','abstract-installed',str(config)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
   display=wait(lambda:next((p.name for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
   owner=subprocess.Popen(['/usr/bin/python3',str(installed/'installed_launcher.py'),'session','--nested'],cwd=base,env=dict(env,WAYLAND_DISPLAY=display,WINIT_UNIX_BACKEND='wayland'),stdout=subprocess.PIPE,stderr=log,start_new_session=True)
   selector=selectors.DefaultSelector();selector.register(owner.stdout,selectors.EVENT_READ);buffer=b'';info=None;end=time.monotonic()+35
   while time.monotonic()<end and info is None:
    assert owner.poll() is None,'Installed owner exited: /tmp/abstract-017-staged-runtime.log'
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
   import sys
   sys.path.insert(0,str(installed))
   from native_compositor import NativeCompositor
   native=NativeCompositor(info['control'])
   before=native.snapshot()
   with open(args.report_dir/'wayland.log','w') as protocol:
    foot=subprocess.Popen([str(args.foot.resolve()),'--title','Mellipi Foot Probe','--app-id','abstract-foot-probe','--term','xterm-256color','/bin/sh','-c','read -r line; printf %s "$line" > "$HOME/typed-result"; sleep 18'],env=dict(env,WAYLAND_DISPLAY=display,WAYLAND_DEBUG='client',LD_LIBRARY_PATH=args.library_path),stdout=protocol,stderr=protocol,start_new_session=True)
    observations=[]
    time.sleep(1)
    sys.path.insert(0,str(ROOT/'tools'))
    from qa_wayland_input import VirtualPointer
    import struct
    keys=VirtualPointer(dict(env,WAYLAND_DISPLAY=next(p.name for p in runtime.glob('wayland-*') if p.name != display and not p.name.endswith('.lock'))))
    keys.click(400,300,width=1024,height=768)
    time.sleep(.3)
    for code in (30,28):
     stamp=int(time.monotonic()*1000)&0xffffffff
     keys.send(keys.keyboard_id,1,struct.pack('=III',stamp,code,1));keys.send(keys.keyboard_id,1,struct.pack('=III',stamp+1,code,0));keys.roundtrip()
    keys.close()

    for i in range(20):
     time.sleep(.5)
     snap=native.snapshot()
     observations.append({'seconds':(i+1)*.5,'process':foot.poll(),'snapshot':snap})
     if foot.poll() is not None:break
    assert (home/'typed-result').read_text()=='a', 'Typed input did not reach Foot'
    protocol.flush()
    events=(args.report_dir/'wayland.log').read_text()
    assert next(i for i,line in enumerate(events.splitlines()) if 'xdg_surface@' in line and '.configure(' in line) < next(i for i,line in enumerate(events.splitlines()) if 'wl_keyboard@' in line and '.enter(' in line), 'Focus arrived before initial configure'
    assert foot.poll() is None, 'Foot exited before regression completed'
    assert any(w.get('app_id')=='abstract-foot-probe' and w.get('active') for w in observations[-1]['snapshot']['windows']), 'Foot never mapped/focused'
    (args.report_dir/'observations.json').write_text(json.dumps({'ready':info,'before':before,'observations':observations},indent=2))
    print(json.dumps({'observations':str(args.report_dir/'observations.json'),'foot_exit':foot.poll(),'last':observations[-1]}))
  finally:
   stop(foot);stop(owner);stop(parent)
   # Owned bus activations may leave disconnected private GIO/document FUSE
   # mounts briefly after process exit. Never touch the user's runtime mounts.
   for name in ('gvfs','doc'):
    subprocess.run(['fusermount3','-uz',str(runtime/name)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   time.sleep(.2)
if __name__=='__main__':main()

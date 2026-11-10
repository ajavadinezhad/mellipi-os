#!/usr/bin/env python3
"""Real installed Fcitx composition on owned native Wayland and D-Bus only."""
import json,os,signal,struct,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT));sys.path.insert(0,str(ROOT/'tools'))
from native_compositor import NativeCompositor
from qa_wayland_input import VirtualPointer

def wait(check,seconds=15):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=check()
  if value:return value
  time.sleep(.04)
 raise AssertionError('Private IME fixture timed out')
def stop(process):
 if process and process.poll() is None:
  try:os.killpg(process.pid,signal.SIGTERM)
  except ProcessLookupError:return
  try:process.wait(timeout=3)
  except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
FIXTURE='''import gi,sys
from pathlib import Path
gi.require_version('Gtk','3.0');from gi.repository import Gtk
w=Gtk.Window(title='Abstract private IME field');w.set_default_size(420,180)
e=Gtk.Entry();w.add(e);e.connect('changed',lambda e:Path(sys.argv[1]).write_text(e.get_text()));w.connect('destroy',Gtk.main_quit);w.show_all();e.grab_focus();Gtk.main()
'''
def inside(base):
 assert os.environ.get('ABSTRACT_PRIVATE_IME_QA')=='1'
 assert os.environ.get('XDG_RUNTIME_DIR')==str(base/'runtime')
 processes=[];pointer=None
 with open('/tmp/abstract-ime-native.log','w') as log:
  runtime=base/'runtime';config=base/'config';config.mkdir();fcitxconfig=config/'fcitx5';fcitxconfig.mkdir()
  (fcitxconfig/'profile').write_text('[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=keyboard-us\n\n[Groups/0/Items/0]\nName=keyboard-us\nLayout=\n\n[GroupOrder]\n0=Default\n')
  parentconfig=base/'sway.conf';parentconfig.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\nfocus_follows_mouse no\n')
  env=dict(os.environ,XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(config),XDG_DATA_HOME=str(base/'data'),XDG_CACHE_HOME=str(base/'cache'),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
  env.update(NO_AT_BRIDGE='1',GIO_USE_VFS='local',GTK_USE_PORTAL='0')
  for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','QT_IM_MODULE','GTK_IM_MODULE','XMODIFIERS'):env.pop(key,None)
  def launch(args,environment=env,output=log):
   p=subprocess.Popen(args,cwd=ROOT,env=environment,stdout=output,stderr=log,start_new_session=True);processes.append(p);return p
  try:
   subprocess.run(['dbus-update-activation-environment','XDG_RUNTIME_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','NO_AT_BRIDGE','GIO_USE_VFS','GTK_USE_PORTAL'],env=env,check=True,timeout=5,stdout=log,stderr=log)
   parent=launch(['bash','-c','source tools/wayland-env.sh;exec sway -c "$1"','abstract-ime',str(parentconfig)])
   outer=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
   nativelog=base/'native.log'
   with nativelog.open('w') as stream:native=launch([str(ROOT/'.native-runtime/bin/orbit-compositor')],dict(env,WAYLAND_DISPLAY=outer.name,WINIT_UNIX_BACKEND='wayland'),stream)
   def ready():
    assert native.poll() is None,nativelog.read_text()
    for line in nativelog.read_text().splitlines():
     try:
      row=json.loads(line)
      if row.get('ready'):return row
     except ValueError:pass
   info=wait(ready);client=NativeCompositor(info['control']);child=dict(env,WAYLAND_DISPLAY=info['wayland_display'])
   ime=launch(['/usr/bin/fcitx5','--disable=notificationitem,notifications,xcb,xim,kimpanel,clipboard'],dict(child,WAYLAND_DEBUG='1'))
   wait(lambda:'get_input_method(' in Path('/tmp/abstract-ime-native.log').read_text(),12);assert ime.poll() is None,'Installed Fcitx failed to start'
   result=base/'text';result.write_text('');app=launch(['/usr/bin/python3','-c',FIXTURE,str(result)],dict(child,GDK_BACKEND='wayland',GTK_IM_MODULE='wayland',WAYLAND_DEBUG='1'))
   row=wait(lambda:next((w for w in client.windows() if w['title']=='Abstract private IME field' and w['rect']['width']>0),None));client.request('focus',id=int(row['id']));time.sleep(.4)
   control=wait(lambda:next(runtime.glob('sway-ipc*.sock'),None));outerenv=dict(env,WAYLAND_DISPLAY=outer.name,SWAYSOCK=str(control));pointer=VirtualPointer(outerenv)
   from sway_events import command as sway_command,request as sway_request
   os.environ['SWAYSOCK']=str(control)
   def host_view(node):
    if str(node.get('name','')).startswith('Orbit Native'):return node
    for row in node.get('nodes',[])+node.get('floating_nodes',[]):
     found=host_view(row)
     if found:return found
   host=wait(lambda:host_view(sway_request(4)));sway_command('[con_id='+str(host['id'])+'] focus');time.sleep(.6)
   def modifiers(mask):pointer.send(pointer.keyboard_id,2,struct.pack('=IIII',mask,0,0,0));pointer.roundtrip()
   def key(code):
    stamp=int(time.monotonic()*1000)&0xffffffff
    pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp,code,1));pointer.send(pointer.keyboard_id,1,struct.pack('=III',stamp+1,code,0));pointer.roundtrip();time.sleep(.08)
   # Send physical modifier events too: the nested compositor maintains
   # its own xkb state instead of inheriting the parent seat's modifier mask.
   def held(code,pressed):
    pointer.send(pointer.keyboard_id,1,struct.pack('=III',int(time.monotonic()*1000)&0xffffffff,code,int(pressed)));pointer.roundtrip();time.sleep(.08)
   held(29,True);held(42,True);modifiers(1|4);key(22)
   held(42,False);held(29,False);modifiers(0)
   for code in (3,7,4,30):key(code) # 263a, a smiling face Unicode code point
   key(28)
   wait(lambda:'☺' in result.read_text(),5)
   log.flush();assert 'commit_string("☺")' in Path('/tmp/abstract-ime-native.log').read_text(),'Text must be committed by the real installed IME protocol, not the widget compose fallback'
   print('PASS installed Fcitx Unicode composition committed into native GTK field',flush=True)
   print(json.dumps(dict(private_bus=True,private_native=True,text=result.read_text(),physical_session_untouched=True)))
  except Exception:
   log.flush();print(Path('/tmp/abstract-ime-native.log').read_text()[-10000:],file=sys.stderr);raise
  finally:
   if pointer:pointer.close()
   for process in reversed(processes):stop(process)
def main():
 if len(sys.argv)==3 and sys.argv[1]=='--private-bus':return inside(Path(sys.argv[2]))
 with tempfile.TemporaryDirectory(prefix='abstract-ime-',ignore_cleanup_errors=True) as temporary:
  base=Path(temporary);runtime=base/'runtime';runtime.mkdir(mode=0o700)
  env={k:v for k,v in os.environ.items() if k not in ('DBUS_SESSION_BUS_ADDRESS','WAYLAND_DISPLAY','DISPLAY','SWAYSOCK','ORBIT_NATIVE_CONTROL','PULSE_SERVER','PIPEWIRE_REMOTE','PIPEWIRE_RUNTIME_DIR','XDG_DESKTOP_PORTAL_DIR')}
  env.update(ABSTRACT_PRIVATE_IME_QA='1',XDG_RUNTIME_DIR=str(runtime),XDG_CONFIG_HOME=str(base/'config'),XDG_DATA_HOME=str(base/'data'),XDG_CACHE_HOME=str(base/'cache'),PULSE_SERVER='unix:'+str(runtime/'no-audio'),PIPEWIRE_RUNTIME_DIR=str(runtime))
  try:return subprocess.call(['dbus-run-session','--','/usr/bin/python3',__file__,'--private-bus',str(base)],env=env)
  finally:
   subprocess.run(['fusermount3','-uz',str(runtime/'doc')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   time.sleep(.2)
if __name__=='__main__':sys.exit(main())

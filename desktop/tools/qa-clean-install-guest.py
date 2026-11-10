#!/usr/bin/env python3
"""Disposable VM guest probes. start-tty intentionally configures ONLY a QA VM."""
import argparse,ctypes,ctypes.util,json,os,shutil,socket,stat,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path('/usr/lib/abstract');SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT

def assert_guest():
 if not Path('/home/abstract/qa-guest.py').is_file() or not Path('/var/lib/cloud/instance').exists() or Path('/etc/hostname').read_text().strip()!='abstract-qa':raise RuntimeError('This action requires the explicitly seeded Mellipi QA VM')

def baseline():
 assert_guest();sys.path.insert(0,str(SOURCE_ROOT));checks={}
 for path in (SOURCE_ROOT/'native_app.py',ROOT/'.native-runtime/bin/orbit-compositor',ROOT/'.lock-runtime/bin/swaylock',Path('/usr/share/wayland-sessions/abstract.desktop'),Path('/etc/pam.d/swaylock')):
  if not path.is_file():raise RuntimeError('Missing prerequisite: '+str(path))
 # Check every packaged ELF, not just entrypoints: private tray/portal/Qt
 # dependencies can otherwise be accidentally supplied by the developer host.
 elfs=[];seen=set();visited=0
 for path in sorted(ROOT.rglob('*')):
  visited+=1
  if visited>20000:raise RuntimeError('Packaged file scan exceeded bound')
  if not path.is_file():continue
  target=path.resolve()
  if target in seen or not target.is_relative_to(ROOT):continue
  with target.open('rb') as source:magic=source.read(4)
  if magic!=b'\x7fELF':continue
  seen.add(target);elfs.append(target)
  if len(elfs)>256:raise RuntimeError('Packaged ELF scan exceeded bound')
 if not elfs:raise RuntimeError('No packaged ELF runtimes found')
 library_dirs=sorted({str(path.parent) for path in elfs})
 environment=dict(os.environ,LD_LIBRARY_PATH=':'.join(library_dirs))
 for binary in elfs:
  value=subprocess.run(['ldd',str(binary)],capture_output=True,text=True,env=environment,timeout=15)
  if 'not found' in value.stdout+value.stderr or value.returncode and 'statically linked' not in value.stdout+value.stderr:raise RuntimeError(str(binary)+': '+value.stdout+value.stderr)
 checks['elf_dependencies']=True
 checks['elf_files']=[str(path.relative_to(ROOT)) for path in elfs]
 from PyQt5.QtWidgets import QApplication
 from PyQt5.QtGui import QImage,QIcon
 from PyQt5.QtCore import QLibraryInfo,QPluginLoader
 os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software';os.environ['ORBIT_QT']='5'
 app=QApplication([])
 plugin=Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))/'wayland-shell-integration/liblayer-shell.so'
 loader=QPluginLoader(str(plugin))
 if not plugin.is_file() or not loader.load():raise RuntimeError('Qt layer-shell plugin unavailable: '+loader.errorString())
 checks['qt_layer_shell_plugin']=True
 image=QImage(str(ROOT/'native/wallpaper.svg'))
 if image.isNull():raise RuntimeError('Qt SVG reader unavailable')
 import icon_theme;icon_theme.configure()
 if QIcon.fromTheme('folder').pixmap(24,24).isNull():raise RuntimeError('Installed fallback icon theme cannot render folder icon')
 checks['qt_svg_and_icon_fallback']=True
 import cairo
 from lock_background import _svg_to_png
 with tempfile.TemporaryDirectory(prefix='abstract-qa-lock-art-') as directory:
  output=Path(directory)/'art.png';_svg_to_png(ROOT/'native/wallpaper.svg',output,320,240)
  if not output.is_file():raise RuntimeError('Themed lock renderer failed')
 checks['themed_lock_svg']=True
 for name in ('x-terminal-emulator','gio','flock','dbus-run-session','swayidle'):
  if not shutil.which(name):raise RuntimeError('Missing required executable: '+name)
 checks['required_commands']=True
 checks['pam_policy_present']=True;checks['pam_authentication']='not tested'
 checks['optional_services']={name:bool(shutil.which(name)) for name in ('nmcli','bluetoothctl','orca','fcitx5')}
 checks['optional_services']['wvkbd']=any(shutil.which(name) for name in ('wvkbd','wvkbd-mobintl','wvkbd-desktop'))
 checks['screen_reader_lock_support']=False;checks['touchscreen_lock_keyboard']=False
 checks['distribution']=Path('/etc/os-release').read_text()
 checks['installed_packages']=subprocess.check_output(['dpkg-query','-W','-f=${Package}=${Version}\n','abstract-shell'],text=True).strip()
 print(json.dumps(checks))

def start_tty():
 assert_guest()
 if os.geteuid()!=0:raise RuntimeError('VM-only getty setup needs guest sudo')
 directory=Path('/etc/systemd/system/getty@tty1.service.d');directory.mkdir(parents=True,exist_ok=True)
 (directory/'abstract-qa.conf').write_text('[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin abstract --noclear %I $TERM\n')
 profile=Path('/home/abstract/.bash_profile')
 if profile.exists():raise RuntimeError('Unexpected preexisting guest profile; preserve it')
 profile.write_text('if [ "$(tty)" = /dev/tty1 ] && [ ! -e "$HOME/.abstract-qa-no-start" ]; then\n if [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bus" ]; then\n  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bus"\n  exec /usr/bin/abstract-session\n else\n  exec dbus-run-session -- /usr/bin/abstract-session\n fi\nfi\n[ ! -f "$HOME/.profile" ] || . "$HOME/.profile"\n')
 import pwd
 user=pwd.getpwnam('abstract');os.chown(profile,user.pw_uid,user.pw_gid)
 # The full profile may have started its guest display manager during APT.
 # Stop only that VM service before testing its independent TTY login.
 manager=subprocess.run(['systemctl','is-active','--quiet','display-manager.service'])
 if manager.returncode==0:subprocess.run(['systemctl','stop','display-manager.service'],check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 switch=shutil.which('chvt')
 if not switch:raise RuntimeError('Guest TTY acceptance needs chvt from kbd; no seat preflight bypass is used')
 subprocess.run([switch,'1'],check=True)
 subprocess.run(['systemctl','restart','getty@tty1.service'],check=True)
 print(json.dumps(dict(guest_getty_configured=True,physical_host_changed=False)))

def session():
 assert_guest();sys.path.insert(0,str(SOURCE_ROOT));found=[]
 for entry in Path('/proc').iterdir():
  if not entry.name.isdigit():continue
  try:
   if entry.stat().st_uid!=os.getuid():continue
   args=(entry/'cmdline').read_bytes().split(b'\0')
   if str(SOURCE_ROOT/'native_app.py').encode() not in args:continue
   env=dict(row.split(b'=',1) for row in (entry/'environ').read_bytes().split(b'\0') if b'=' in row)
   if env.get(b'ORBIT_NATIVE_CONTROL') and not env.get(b'ORBIT_NESTED'):found.append((entry,env))
  except OSError:continue
 if len(found)!=1:raise RuntimeError('VM native shell not ready')
 entry,env=found[0]
 for key in ('XDG_RUNTIME_DIR','WAYLAND_DISPLAY','ORBIT_NATIVE_CONTROL'):
  os.environ[key]=env[key.encode()].decode()
 runtime=Path(os.environ['XDG_RUNTIME_DIR']);info=runtime.stat()
 if info.st_uid!=os.getuid() or info.st_mode&0o077:raise RuntimeError('Runtime directory ownership/mode invalid')
 from native_compositor import NativeCompositor
 compositor=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']);status=compositor.status()
 if not status.get('capabilities',{}).get('login_session'):raise RuntimeError('Expected real VM DRM login, not nested preview')
 inputs=compositor.request('input_get').get('inputs',[])
 if not any(row.get('type')=='keyboard' for row in inputs):raise RuntimeError('Native VM keyboard inventory is not ready before first input')
 from control import socket_path
 with socket.socket(socket.AF_UNIX) as connection:
  connection.settimeout(4);connection.connect(socket_path());connection.sendall(b'status\n');data=b''
  while chunk:=connection.recv(65536):
   data+=chunk
   if len(data)>1024*1024:raise RuntimeError('Oversized shell reply')
 shell=json.loads(data)
 if shell['qml_errors']:raise RuntimeError(str(shell['qml_errors']))
 print(json.dumps(dict(native_drm_login=True,shell_ready=True,qml_errors=[],runtime_private=True,secure_lock_capability=status['capabilities'].get('secure_lock',False),locked=status['locked'],wayland_display=status['wayland_display'],workspace=status['workspace'],output_count=len(compositor.snapshot().get('outputs',[])),input_inventory_before_first_key=len(inputs),vm_only=True)))

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=('baseline','start-tty','session'));args=parser.parse_args()
 {'baseline':baseline,'start-tty':start_tty,'session':session}[args.phase]()
if __name__=='__main__':main()

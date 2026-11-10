"""Stage-only package tests; never install or change this computer's session."""
import importlib.util,os,shutil,struct,subprocess,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from installed_launcher import user_environment
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('package_builder',ROOT/'tools/build-desktop-package.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
class DesktopPackageTest(unittest.TestCase):
 def test_private_xdg_paths_and_explicit_overrides(self):
  env=user_environment({'HOME':'/example','XDG_DATA_HOME':'/private/data','XDG_CONFIG_HOME':'/private/config'})
  self.assertEqual(env['ORBIT_DATA'],'/private/data/abstract');self.assertEqual(env['ORBIT_SETTINGS_FILE'],'/private/config/abstract/settings.json')
  self.assertEqual(user_environment({'HOME':'/example','ORBIT_DATA':'/chosen'})['ORBIT_DATA'],'/chosen')
 def test_relative_or_empty_xdg_paths_fall_back_and_relative_explicit_state_is_rejected(self):
  env=user_environment({'HOME':'/example','XDG_DATA_HOME':'relative','XDG_CONFIG_HOME':''})
  self.assertEqual(env['ORBIT_DATA'],'/example/.local/share/abstract')
  self.assertEqual(env['XDG_CONFIG_HOME'],'/example/.config')
  for key in ('ORBIT_DATA','ORBIT_SETTINGS_FILE','ORBIT_FOLD_STATE'):
   with self.subTest(key=key),self.assertRaises(ValueError):user_environment({'HOME':'/example',key:'relative'})
 def test_stage_is_self_contained_and_uses_no_checkout_in_launch_entries(self):
  with tempfile.TemporaryDirectory() as directory:
   base=Path(directory);root=base/'checkout';root.mkdir()
   for name in builder.RUNTIME_FILES:
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture-binary')
   for folder in ('native','themes','src/session/configs/xdg-desktop-portal','tools'): (root/folder).mkdir(parents=True,exist_ok=True)
   (root/'native/Test.qml').write_text('import QtQuick 2.15\nItem{}')
   for name in ('run-native-session.sh','run-native-shell.sh','README.md','src/installed_launcher.py','tools/wayland-env.sh','tools/qt5-env.sh','tools/native-output-power.py','tools/display-watchdog.py','tools/migrate-user-state.py','src/session/configs/xdg-desktop-portal/orbit-portals.conf'):
    (root/name).write_text('fixture')
   with patch.object(builder,'elf_dependencies',return_value=['libfixture-runtime (>= 1.0)']):stage=builder.stage_package(base/'stage','0.1.0','amd64',root)
   self.assertTrue((stage/'usr/lib/abstract/.native-runtime/bin/orbit-compositor').is_file())
   self.assertTrue((stage/'usr/lib/abstract/installed_launcher.py').is_file())
   self.assertTrue((stage/'usr/lib/abstract/session/configs/xdg-desktop-portal/orbit-portals.conf').is_file())
   self.assertFalse((stage/'usr/lib/abstract/src').exists())
   for name in ('usr/bin/abstract-session','usr/bin/abstractctl','usr/share/wayland-sessions/abstract.desktop','usr/share/applications/orbit-settings.desktop'):
    content=(stage/name).read_text();self.assertNotIn(str(root),content);self.assertIn('/usr/',content)
   self.assertFalse((stage/'etc/pam.d/swaylock').exists())
   # Exercise maintainer cleanup against fake commands, never host services.
   commands=base/'commands';commands.mkdir();calls=base/'calls'
   for command in ('deb-systemd-helper','systemctl','udevadm'):
    script=commands/command;script.write_text('#!/bin/sh\nprintf \"%s:%s\\n\" '+command+' \"$*\" >> \"$CALL_LOG\"\n');script.chmod(0o755)
   env=dict(os.environ,PATH=str(commands)+':/usr/bin:/bin',CALL_LOG=str(calls))
   subprocess.run(['/bin/sh',str(stage/'DEBIAN/postrm'),'upgrade'],env=env,check=True);self.assertFalse(calls.exists())
   subprocess.run(['/bin/sh',str(stage/'DEBIAN/postrm'),'purge'],env=env,check=True)
   self.assertIn('deb-systemd-helper:purge abstract-charge-limits.service',calls.read_text())
   self.assertIn('systemctl:daemon-reload',calls.read_text())
   for path in stage.rglob('*'):
    if not path.is_symlink():self.assertEqual(path.stat().st_mode & 0o022,0,str(path))
   control=(stage/'DEBIAN/control').read_text();self.assertIn('python3-pyqt5.qtquick',control);self.assertNotIn('mintupdate',control);self.assertIn('qtwayland5',control);self.assertIn('pipewire-pulse | pulseaudio',control);self.assertIn('pkexec',control)

 def test_elf_architecture_rejects_mislabeled_foreign_and_truncated_binaries(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);path=root/'program'
   shutil.copy2('/usr/bin/true',path)
   self.assertEqual(builder.packaged_elfs(root,'amd64'),[path])
   with self.assertRaisesRegex(ValueError,'baseline'):builder.packaged_elfs(root,'arm64')
   value=bytearray(path.read_bytes());value[18:20]=struct.pack('<H',183);path.write_bytes(value)
   with self.assertRaisesRegex(ValueError,'does not match'):builder.packaged_elfs(root,'amd64')
   path.write_bytes(b'\x7fELF')
   with self.assertRaisesRegex(ValueError,'does not match'):builder.packaged_elfs(root,'amd64')
 def test_explicit_render_and_tray_dependencies_and_opt_in_desktop_profile(self):
  for name in ('gir1.2-rsvg-2.0','librsvg2-common','libqt5svg5','libxcb-damage0','libxcb-composite0'):self.assertIn(name,builder.DEPENDENCIES)
  self.assertNotIn('lightdm',builder.DEPENDENCIES)
  with tempfile.TemporaryDirectory() as directory:
   stage=builder.stage_desktop_package(Path(directory)/'desktop','0.1.5');control=(stage/'DEBIAN/control').read_text()
   for name in ('mellipi-shell (= 0.1.5)','lightdm','lightdm-gtk-greeter','xserver-xorg','network-manager','foot','mousepad','epiphany-browser','synaptic','wvkbd','orca','fcitx5','fcitx5-config-qt','ddcutil','gnome-system-tools'):self.assertIn(name,control)
   self.assertFalse((stage/'DEBIAN/postinst').exists());self.assertFalse((stage/'etc/pam.d').exists());self.assertFalse((stage/'etc/lightdm/lightdm.conf').exists());self.assertFalse((stage/'etc/lightdm/lightdm-gtk-greeter.conf').exists())
   for path in stage.rglob('*'):self.assertEqual(path.stat().st_mode & 0o022,0,str(path))
 def test_shlibdeps_includes_all_elfs_and_private_search_paths_without_suppressing_missing_info(self):
  with tempfile.TemporaryDirectory() as directory:
   stage=Path(directory);paths=[]
   for name in builder.RUNTIME_FILES:
    path=stage/'usr/lib/abstract'/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2('/usr/bin/true',path);paths.append(path)
   library=stage/'usr/lib/abstract/.tray-runtime/lib/libFixture.so.5';library.parent.mkdir(parents=True);shutil.copy2('/usr/bin/true',library);paths.append(library)
   def dynamic(args,**kwargs):return '(SONAME) Library soname: [libFixture.so.5]' if args[-1]==str(library) else ''
   def resolver(args,**kwargs):
    self.assertNotIn('--ignore-missing-info',args);self.assertIn('-xmellipi-shell',args);self.assertIn('-l'+str(library.parent),args)
    self.assertEqual({v[2:] for v in args if v.startswith('-e')},{str(path) for path in paths})
    self.assertIn('libFixture 5 mellipi-shell (= 0.1.5)',Path(next(v[2:] for v in args if v.startswith('-L'))).read_text())
    return type('Result',(),dict(returncode=0,stdout='shlibs:Depends=libc6 (>= 2.34), libxcb-damage0\n',stderr=''))()
   with patch.object(builder.subprocess,'check_output',side_effect=dynamic),patch.object(builder.subprocess,'run',side_effect=resolver):
    self.assertEqual(builder.elf_dependencies(stage,'amd64','0.1.5'),['libc6 (>= 2.34)','libxcb-damage0'])

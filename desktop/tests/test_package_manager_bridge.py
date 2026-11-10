"""Privileged GUI bridge validation; no privileged processes or runtime paths."""
import importlib.machinery,importlib.util,stat,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('package_manager_bridge',str(ROOT/'packaging/abstract-synaptic-root'))
spec=importlib.util.spec_from_loader(loader.name,loader);bridge=importlib.util.module_from_spec(spec);loader.exec_module(bridge)
class PackageManagerBridgeTests(unittest.TestCase):
 def metadata(self,path):
  path=str(path)
  if path=='/run/user/1000':return SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=1000)
  if path=='/run/user/1000/wayland-1':return SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=1000)
  raise FileNotFoundError(path)
 def test_authenticated_socket_accepts_relative_or_exact_absolute_name(self):
  with patch.object(bridge.Path,'lstat',lambda path:self.metadata(path)):
   for display in ('wayland-1','/run/user/1000/wayland-1'):self.assertEqual(bridge.checked_display('1000','/run/user/1000',display),'/run/user/1000/wayland-1')
 def test_rejects_missing_system_or_overflowing_caller(self):
  with patch.object(bridge.Path,'lstat',side_effect=AssertionError('Unexpected filesystem access')):
   for uid in ('','0','999','65534','2147483648','-1000','1000x','1000\n'):
    with self.subTest(uid=uid),self.assertRaises(ValueError):bridge.checked_display(uid,'/run/user/1000','wayland-1')
 def test_rejects_runtime_and_display_escape(self):
  with patch.object(bridge.Path,'lstat',lambda path:self.metadata(path)):
   for runtime in ('/tmp/runtime','/run/user/1001','/run/user/1000/','/run/user/1000/../1000'):
    with self.subTest(runtime=runtime),self.assertRaises(ValueError):bridge.checked_display('1000',runtime,'wayland-1')
   for display in ('../wayland-1','/run/user/1001/wayland-1','wayland-1/../wayland-1','wayland-1\n','/tmp/wayland-1','wayland-1/child',''):
    with self.subTest(display=display),self.assertRaises(ValueError):bridge.checked_display('1000','/run/user/1000',display)
 def test_rejects_symlink_wrong_owner_or_public_runtime(self):
  for mode,owner in [(stat.S_IFLNK|0o777,1000),(stat.S_IFDIR|0o755,1000),(stat.S_IFDIR|0o700,0),(stat.S_IFREG|0o700,1000)]:
   with self.subTest(mode=mode,owner=owner),patch.object(bridge.Path,'lstat',return_value=SimpleNamespace(st_mode=mode,st_uid=owner)),self.assertRaises(ValueError):bridge.checked_display('1000','/run/user/1000','wayland-1')
 def test_rejects_symlink_regular_file_or_foreign_socket(self):
  for mode,owner in [(stat.S_IFLNK|0o777,1000),(stat.S_IFREG|0o600,1000),(stat.S_IFSOCK|0o600,0)]:
   def metadata(path):return self.metadata(path) if str(path)=='/run/user/1000' else SimpleNamespace(st_mode=mode,st_uid=owner)
   with self.subTest(mode=mode,owner=owner),patch.object(bridge.Path,'lstat',metadata),self.assertRaises(ValueError):bridge.checked_display('1000','/run/user/1000','wayland-1')
 def test_rejects_unprivileged_or_extra_arguments_before_launch(self):
  with patch.object(bridge.subprocess,'run') as launch,patch.object(bridge.os,'geteuid',return_value=1000),self.assertRaises(ValueError):bridge.run(['/run/user/1000','wayland-1'],{'PKEXEC_UID':'1000'})
  launch.assert_not_called()
  with patch.object(bridge.os,'geteuid',return_value=0),patch.object(bridge.subprocess,'run') as launch:
   for arguments in ([],['/run/user/1000'],['/run/user/1000','wayland-1','/bin/sh']):
    with self.assertRaises(ValueError):bridge.run(arguments,{'PKEXEC_UID':'1000'})
   launch.assert_not_called()
 def test_fixed_program_clean_environment_private_state_and_cleanup(self):
  original=tempfile.TemporaryDirectory;seen=[]
  hostile={'PKEXEC_UID':'1000','PATH':'/evil','HOME':'/evil','LD_PRELOAD':'/evil.so','PYTHONPATH':'/evil','GTK_PATH':'/evil','GTK_MODULES':'/evil','GIO_EXTRA_MODULES':'/evil','XAUTHORITY':'/evil','DISPLAY':':4','DBUS_SESSION_BUS_ADDRESS':'unix:path=/evil','XDG_CONFIG_HOME':'/evil','GDK_BACKEND':'x11'};before=dict(hostile)
  def launch(argv,**kwargs):
   seen.append((argv,kwargs));runtime=Path(kwargs['env']['XDG_RUNTIME_DIR'])
   self.assertTrue(runtime.is_dir());self.assertEqual(stat.S_IMODE(runtime.stat().st_mode),0o700)
   self.assertEqual(argv,['/usr/sbin/synaptic']);self.assertEqual(kwargs['cwd'],'/');self.assertFalse(kwargs['check'])
   env=kwargs['env'];self.assertEqual(env['GDK_BACKEND'],'wayland');self.assertEqual(env['WAYLAND_DISPLAY'],'/run/user/1000/wayland-1');self.assertEqual(env['HOME'],'/root')
   self.assertEqual(set(env),{'PATH','HOME','USER','LOGNAME','LANG','GDK_BACKEND','WAYLAND_DISPLAY','XDG_RUNTIME_DIR'})
   return SimpleNamespace(returncode=23)
  with original() as base,patch.object(bridge.os,'geteuid',return_value=0),patch.object(bridge.Path,'lstat',lambda path:self.metadata(path)),patch.object(bridge.tempfile,'TemporaryDirectory',side_effect=lambda **kw:original(prefix=kw['prefix'],dir=base)),patch.object(bridge.subprocess,'run',side_effect=launch):self.assertEqual(bridge.run(['/run/user/1000','wayland-1'],hostile),23)
  self.assertEqual(hostile,before);self.assertEqual(len(seen),1);self.assertFalse(Path(seen[0][1]['env']['XDG_RUNTIME_DIR']).exists())
 def test_policy_authenticates_fixed_helper_without_gui_environment_forwarding(self):
  root=ET.parse(ROOT/'packaging/org.abstract.package-manager.policy').getroot();actions=root.findall('action');self.assertEqual(len(actions),1);action=actions[0]
  self.assertEqual(action.attrib['id'],'org.abstract.package-manager')
  self.assertEqual({e.attrib['key']:e.text for e in action.findall('annotate')},{'org.freedesktop.policykit.exec.path':'/usr/lib/abstract/abstract-synaptic-root'})
  self.assertEqual({e.tag:e.text for e in action.find('defaults')},{'allow_any':'auth_admin','allow_inactive':'auth_admin','allow_active':'auth_admin'})
  self.assertTrue((ROOT/'packaging/abstract-synaptic-root').read_text().startswith('#!/usr/bin/python3 -I\n'))
if __name__=='__main__':unittest.main()

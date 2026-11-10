"""Native package entry points retain discovery and GIO launch semantics."""
import unittest
from unittest.mock import patch
import desktop
from desktop_tools import discover_tools
class PackageManagerDiscoveryTests(unittest.TestCase):
 def test_native_synaptic_uses_bridge_and_non_native_keeps_distro_launcher(self):
  env={'ORBIT_NATIVE_CONTROL':'/private/native.sock','WAYLAND_DISPLAY':'wayland-1'}
  which=lambda name:'/usr/bin/'+name if name in ('abstract-package-manager','synaptic','synaptic-pkexec') else None
  for kind in ('updates','software'):self.assertEqual(discover_tools(env,which)[kind]['command'],['abstract-package-manager'])
  self.assertEqual(discover_tools({},which)['updates']['command'],['synaptic-pkexec'])
 def test_bridge_without_synaptic_does_not_claim_frontend_available(self):
  env={'ORBIT_NATIVE_CONTROL':'/private/native.sock','WAYLAND_DISPLAY':'wayland-1'}
  rows=discover_tools(env,lambda name:'/usr/bin/abstract-package-manager' if name=='abstract-package-manager' else None)
  self.assertFalse(rows['updates']['available']);self.assertFalse(rows['software']['available'])
 def test_other_frontends_keep_priority(self):
  env={'ORBIT_NATIVE_CONTROL':'/private/native.sock','WAYLAND_DISPLAY':'wayland-1'}
  which=lambda name:'/usr/bin/'+name if name in ('abstract-package-manager','synaptic','gnome-software') else None
  self.assertEqual(discover_tools(env,which)['updates']['command'],['gnome-software','--mode=updates'])
 def test_only_distro_synaptic_entry_gets_private_gio_launch_path(self):
  env={'ORBIT_NATIVE_CONTROL':'/private/native.sock','WAYLAND_DISPLAY':'wayland-1'};app={'id':'synaptic.desktop','path':'/usr/share/applications/synaptic.desktop'}
  with patch.object(desktop.Path,'is_file',return_value=True),patch.object(desktop.shutil,'which',side_effect=lambda n:'/usr/bin/'+n):
   self.assertEqual(desktop.application_launch_path(app,env),'/usr/lib/abstract/synaptic-native.desktop')
   self.assertEqual(desktop.application_launch_path(app,{}),app['path'])
   custom=dict(app,path='/home/example/.local/share/applications/synaptic.desktop');self.assertEqual(desktop.application_launch_path(custom,env),custom['path'])
   other={'id':'other.desktop','path':'/usr/share/applications/other.desktop'};self.assertEqual(desktop.application_launch_path(other,env),other['path'])
if __name__=='__main__':unittest.main()

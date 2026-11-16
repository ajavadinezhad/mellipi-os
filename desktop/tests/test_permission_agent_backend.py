"""Noble polkit compatibility stays within its actual session child launch."""
import os,unittest
from unittest.mock import patch
from session import autostart
from session.assistive import permission_agent,service_environment
AGENT='/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1'
class PermissionAgentBackendTests(unittest.TestCase):
 def test_native_agent_child_uses_x11_without_mutating_caller_or_other_services(self):
  env={'ORBIT_NATIVE_CONTROL':'/run/user/1000/native.sock','DISPLAY':':2','WAYLAND_DISPLAY':'wayland-1','GDK_BACKEND':'wayland'};original=dict(env);calls=[]
  commands=[[AGENT],['fcitx5'],['/usr/lib/polkit-mate/polkit-mate-authentication-agent-1']]
  with patch.dict(os.environ,env,clear=True),patch.object(autostart,'optional_service_commands',return_value=commands),patch('session.xdg_autostart.running_executables',return_value=set()),patch('desktop.application_environment',side_effect=lambda:dict(env)):
   autostart.launch_optional_services(lambda command,environment:calls.append((command,environment)))
   self.assertEqual(dict(os.environ),env)
  self.assertEqual(env,original);self.assertEqual(calls[0][1]['GDK_BACKEND'],'x11');self.assertEqual(calls[0][1]['DISPLAY'],':2');self.assertEqual(calls[1][1]['GDK_BACKEND'],'wayland')
 def test_only_known_agent_native_local_display_changes(self):
  base={'ORBIT_NATIVE_CONTROL':'/private/native.sock','DISPLAY':':3','GDK_BACKEND':'wayland'}
  for command in [['lxqt-policykit-agent'],['lxpolkit'],['fcitx5'],['polkit-mate-authentication-agent-1']]:self.assertEqual(service_environment(command,base),base)
  for env in [{k:v for k,v in base.items() if k!='ORBIT_NATIVE_CONTROL'},{k:v for k,v in base.items() if k!='DISPLAY'},dict(base,DISPLAY='remote:1')]:self.assertEqual(service_environment([AGENT],env),env)
 def test_custom_agent_is_experimental_and_never_selected_for_nested_sessions(self):
  native={'ORBIT_NATIVE_CONTROL':'/private/native.sock','WAYLAND_DISPLAY':'wayland-1',
          'MELLIPI_NATIVE_AUTH':'1'}
  with patch('session.assistive.shutil.which',return_value=AGENT),patch('session.assistive.Path.is_file',return_value=True),patch('session.assistive.os.access',return_value=True):
   self.assertTrue(permission_agent(native)[0].endswith('/mellipi-auth-agent'))
   self.assertEqual(permission_agent(native)[1:], [AGENT])
   self.assertEqual(permission_agent(dict(native,ORBIT_NESTED='1')), [AGENT])
   self.assertEqual(permission_agent(dict(native,MELLIPI_NATIVE_AUTH='0')), [AGENT])
if __name__=='__main__':unittest.main()

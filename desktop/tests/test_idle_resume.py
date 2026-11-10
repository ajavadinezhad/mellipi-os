import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import idle_policy

class IdleResumeTests(unittest.TestCase):
 def test_native_resume_listener_survives_disabled_timers(self):
  values=dict(idleLockEnabled=False,lockBeforeSleep=False,idleLockMinutes=10,displayOffMinutes=0)
  self.assertEqual(idle_policy.policy_command(values),[])
  command=idle_policy.policy_command(values,native=True)
  self.assertEqual(command[:3],['swayidle','-w','after-resume'])
  self.assertTrue(command[3].endswith('native-output-power.py resume'))
 def test_idle_child_keeps_actual_theme_without_provider_secrets(self):
  launched=[]
  def spawn(command,**kwargs):
   launched.append((command,kwargs));return SimpleNamespace(poll=lambda:None)
  prefs=SimpleNamespace(values=dict(idleLockEnabled=True,lockBeforeSleep=True,idleLockMinutes=10,displayOffMinutes=0),path=Path('/tmp/chosen-theme.json'))
  obj=idle_policy.IdlePolicy(prefs,spawn=spawn,availability=lambda:True,environment={'SWAYSOCK':'/tmp/private-sway','ORBIT_SETTINGS_FILE':'/tmp/wrong.json','ORBIT_DATA':'/tmp/data','ORBIT_API_KEY':'secret','XDG_CONFIG_HOME':'/tmp/config'})
  env=launched[0][1]['env']
  self.assertEqual(env['ORBIT_SETTINGS_FILE'],str(prefs.path));self.assertEqual(env['ORBIT_DATA'],'/tmp/data')
  self.assertEqual(env['XDG_CONFIG_HOME'],'/tmp/config');self.assertNotIn('ORBIT_API_KEY',env);obj.process=None
 def test_resume_helper_typed_dispatch_and_transient_retry(self):
  path=Path(__file__).resolve().parents[1]/'tools/native-output-power.py'
  spec=importlib.util.spec_from_file_location('resume_helper',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  calls=[]
  class Client:
   def __init__(self,path):pass
   def request(self,*args,**kwargs):
    calls.append((args,kwargs))
    if len(calls)==1:raise RuntimeError('Seat is inactive')
  with patch.object(module,'NativeCompositor',Client),patch.object(module.sys,'argv',['helper','resume']),patch.dict(module.os.environ,{'ORBIT_NATIVE_CONTROL':'/tmp/private-native'}),patch.object(module.time,'sleep') as sleep:self.assertEqual(module.main(),0)
  self.assertEqual(calls,[(('output_resume',),{}),(('output_resume',),{})]);sleep.assert_called_once_with(.1)
  class Denied(Client):
   def request(self,*args,**kwargs):raise RuntimeError('unsupported operation')
  with patch.object(module,'NativeCompositor',Denied),patch.object(module.sys,'argv',['helper','resume']),patch.dict(module.os.environ,{'ORBIT_NATIVE_CONTROL':'/tmp/private-native'}),patch.object(module.time,'sleep') as sleep:
   with self.assertRaisesRegex(RuntimeError,'unsupported operation'):module.main()
  sleep.assert_not_called()
 def test_resume_retries_socket_errors_but_power_off_does_not(self):
  path=Path(__file__).resolve().parents[1]/'tools/native-output-power.py'
  spec=importlib.util.spec_from_file_location('resume_socket_helper',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  ready=SimpleNamespace(request=lambda *args,**kwargs:None)
  for mode,retry in [('resume',True),('off',False)]:
   with patch.object(module,'NativeCompositor',side_effect=[OSError('temporary socket timeout'),ready]) as client,patch.object(module.sys,'argv',['helper',mode]),patch.dict(module.os.environ,{'ORBIT_NATIVE_CONTROL':'/tmp/private-native'}),patch.object(module.time,'sleep') as sleep:
    if retry:self.assertEqual(module.main(),0);self.assertEqual(client.call_count,2);sleep.assert_called_once_with(.1)
    else:
     with self.assertRaises(OSError):module.main()
     sleep.assert_not_called()
if __name__=='__main__':unittest.main()

import importlib.util
import threading
import time
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
 def test_exited_idle_child_restarts_with_bounded_backoff(self):
  from qt_compat import QApplication
  app=QApplication.instance() or QApplication([])
  children=[]
  class Child:
   def __init__(self):self.exited=threading.Event()
   def wait(self,timeout=None):self.exited.wait(timeout);return 1
   def poll(self):return 1 if self.exited.is_set() else None
   def terminate(self):self.exited.set()
  def spawn(*args,**kwargs):
   children.append(Child());return children[-1]
  def until(predicate):
   deadline=time.monotonic()+2
   while not predicate() and time.monotonic()<deadline:
    app.processEvents();time.sleep(.005)
   self.assertTrue(predicate())
  prefs=SimpleNamespace(values=dict(idleLockEnabled=True,lockBeforeSleep=True,idleLockMinutes=10,displayOffMinutes=0))
  with patch.object(idle_policy.IdlePolicy,'RESTART_DELAYS',(1,2)):
   obj=idle_policy.IdlePolicy(prefs,spawn=spawn,availability=lambda:True,environment={'SWAYSOCK':'/tmp/private-sway'})
   try:
    self.assertTrue(obj.state['running'])
    for count in (2,3):
     children[-1].exited.set()
     until(lambda:len(children)==count)
     self.assertTrue(obj.state['running'])
    children[-1].exited.set()
    until(lambda:'check Lock settings' in obj.state['error'])
    self.assertFalse(obj.state['running'])
    self.assertEqual(len(children),3)
   finally:obj.close()
 def test_real_idle_child_survives_startup_worker_and_restarts(self):
  from qt_compat import QApplication
  app=QApplication.instance() or QApplication([])
  prefs=SimpleNamespace(values={})
  def until(predicate):
   deadline=time.monotonic()+3
   while time.monotonic()<deadline:
    app.processEvents()
    if predicate():return
    time.sleep(.005)
   self.fail('Idle child did not reach expected state')
  with patch.object(idle_policy,'policy_command',return_value=['/usr/bin/sleep','20']):
   obj=idle_policy.IdlePolicy(prefs,availability=lambda:True,environment={'SWAYSOCK':'/tmp/private-sway'})
   try:
    until(lambda:obj.state['running'])
    first=obj.process
    deadline=time.monotonic()+.15
    while time.monotonic()<deadline:
     app.processEvents();time.sleep(.005)
    self.assertIs(obj.process,first)
    self.assertIsNone(first.poll())
    first.terminate()
    until(lambda:obj.state['running'] and obj.process is not first)
    second=obj.process
   finally:obj.close()
   until(lambda:second.poll() is not None)
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

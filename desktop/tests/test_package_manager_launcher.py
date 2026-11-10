"""The unprivileged wrapper must remain the live parent of pkexec."""
import contextlib,io,os,runpy,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
WRAPPER=Path(__file__).resolve().parents[1]/'packaging/abstract-package-manager'
class PackageManagerLauncherTests(unittest.TestCase):
 def invoke(self,environment,result):
  with patch.dict(os.environ,environment,clear=True),patch('os.path.isfile',return_value=True),patch('os.execv',side_effect=AssertionError('Replacing the wrapper would lose its live-parent boundary')),patch('subprocess.run',return_value=SimpleNamespace(returncode=result)) as launch,self.assertRaises(SystemExit) as exit:
   runpy.run_path(str(WRAPPER),run_name='__main__')
  self.assertEqual(exit.exception.code,result)
  return launch
 def test_native_wrapper_waits_for_fixed_authenticated_child_and_propagates_cancel(self):
  env={'WAYLAND_DISPLAY':'wayland-1','XDG_RUNTIME_DIR':'/run/user/1000','ORBIT_NATIVE_CONTROL':'/private/native.sock'}
  launch=self.invoke(env,126)
  self.assertEqual(launch.call_count,1)
  self.assertEqual(launch.call_args.args[0],['/usr/bin/pkexec','/usr/lib/abstract/abstract-synaptic-root','/run/user/1000','wayland-1'])
  self.assertIs(launch.call_args.kwargs.get('check'),False)
  self.assertFalse(launch.call_args.kwargs.get('start_new_session',False))
 def test_non_wayland_path_retains_the_distribution_wrapper_and_exit_status(self):
  launch=self.invoke({'DISPLAY':':1'},7)
  self.assertEqual(launch.call_args.args[0],['/usr/bin/synaptic-pkexec'])
 def test_missing_frontend_fails_without_spawning_authentication(self):
  with patch('os.path.isfile',return_value=False),patch('subprocess.run') as launch,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exit:runpy.run_path(str(WRAPPER),run_name='__main__')
  self.assertEqual(exit.exception.code,1);launch.assert_not_called()
 def test_real_child_observes_live_wrapper_parent_until_completion(self):
  # Map only the fixed pkexec invocation to an ordinary local Python child.
  # This executes the actual wrapper in a separate process without privilege.
  with tempfile.TemporaryDirectory(prefix='abstract-launch-parent-') as directory:
   base=Path(directory);marker=base/'child-ready';runner=base/'runner.py';child=base/'child.py'
   child.write_text('import os,sys,time\nfrom pathlib import Path\np=os.getppid();os.kill(p,0);Path(sys.argv[1]).write_text(str(p));time.sleep(.4);raise SystemExit(23)\n')
   runner.write_text('import os,runpy,subprocess,sys\nfrom unittest.mock import patch\noriginal=subprocess.run\ndef child(argv,**kwargs):\n assert argv==["/usr/bin/pkexec","/usr/lib/abstract/abstract-synaptic-root","/run/user/1000","wayland-1"],argv\n return original([sys.executable,sys.argv[2],sys.argv[3]],**kwargs)\nwith patch("os.path.isfile",return_value=True),patch("subprocess.run",side_effect=child),patch("os.execv",side_effect=AssertionError("Wrapper must wait")):\n runpy.run_path(sys.argv[1],run_name="__main__")\n')
   process=subprocess.Popen([sys.executable,str(runner),str(WRAPPER),str(child),str(marker)],env=dict(os.environ,WAYLAND_DISPLAY='wayland-1',XDG_RUNTIME_DIR='/run/user/1000'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   try:
    end=time.monotonic()+4
    while not marker.exists() and process.poll() is None and time.monotonic()<end:time.sleep(.01)
    self.assertTrue(marker.exists(),'Wrapper failed to dispatch its child')
    self.assertEqual(int(marker.read_text()),process.pid);self.assertIsNone(process.poll())
    stdout,stderr=process.communicate(timeout=4);self.assertEqual(process.returncode,23,(stdout,stderr))
   finally:
    if process.poll() is None:process.kill();process.wait(timeout=2)
if __name__=='__main__':unittest.main()

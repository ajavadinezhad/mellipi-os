"""No display/login is started; inspect exact post-authentication exec routing."""
import importlib.machinery,importlib.util,os,unittest
from pathlib import Path
from unittest.mock import patch
p=Path(__file__).resolve().parents[1]/'tools/mellipi-session-wrapper'
loader=importlib.machinery.SourceFileLoader('recovery_dispatcher',str(p));spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class RecoveryDispatcherTests(unittest.TestCase):
    def route(self,arguments,environment=None):
        env={'DISPLAY':':7','XAUTHORITY':'/run/user/1000/test-cookie','HOME':'/home/test','XDG_SESSION_DESKTOP':'mellipi-recovery',**(environment or {})}
        with patch.object(m.os,'geteuid',return_value=1000),patch.object(m.sys,'argv',['mellipi-session-wrapper',*arguments]),patch.dict(os.environ,env,clear=True),patch.object(m.os,'execve') as execute:
            m.main()
        execute.assert_called_once();return execute.call_args.args,env
    def test_only_exact_recovery_exec_bypasses_normal_user_scripts(self):
        (path,arguments,environment),original=self.route([m.RECOVERY])
        self.assertEqual(path,m.RECOVERY);self.assertEqual(arguments,[m.RECOVERY]);self.assertEqual(environment,original)
    def test_normal_session_arguments_and_environment_are_unchanged(self):
        values=['/usr/bin/mellipi-session','--check-login']
        (path,arguments,environment),original=self.route(values,{'DESKTOP_SESSION':'abstract','CUSTOM_SETTING':'preserve'})
        self.assertEqual(path,m.NORMAL);self.assertEqual(arguments,[m.NORMAL,*values]);self.assertEqual(environment,original)
    def test_lookalikes_shell_strings_and_extra_arguments_do_not_get_bypass(self):
        for args in ([m.RECOVERY,'--anything'],[m.RECOVERY+'; echo unwanted'],['mellipi-recovery-session'],['/tmp/mellipi-recovery-session'],['/bin/sh','-c',m.RECOVERY],[]):
            (path,arguments,_),_=self.route(args);self.assertEqual(path,m.NORMAL);self.assertEqual(arguments,[m.NORMAL,*args])
    def test_root_invocation_stops_before_exec(self):
        with patch.object(m.os,'geteuid',return_value=0),patch.object(m.os,'execve') as execute,self.assertRaises(SystemExit):m.main()
        execute.assert_not_called()

if __name__=='__main__':unittest.main()

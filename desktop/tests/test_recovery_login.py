import importlib.machinery,importlib.util,os,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
path=Path(__file__).resolve().parents[1]/'tools/mellipi-recovery-session'
loader=importlib.machinery.SourceFileLoader('recovery_login',str(path));spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class RecoveryLoginTests(unittest.TestCase):
    def test_console_starts_at_root_when_existing_home_is_inaccessible(self):
        import recovery_console
        with patch.object(recovery_console.os,'geteuid',return_value=1000),patch.object(recovery_console.os,'getuid',return_value=1000),patch.object(recovery_console.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir='/home/repair-me')),patch.object(recovery_console.os.path,'isdir',return_value=True),patch.object(recovery_console,'focus_terminal'),patch.object(recovery_console.os,'chdir',side_effect=[PermissionError('inaccessible home'),None]) as chdir,patch.object(recovery_console.os,'execve') as execute,patch('builtins.print'):
            recovery_console.main()
        self.assertEqual([c.args for c in chdir.call_args_list],[('/home/repair-me',),('/',)])
        path,args,env=execute.call_args.args;self.assertEqual(path,'/bin/bash');self.assertEqual(env['HOME'],'/home/repair-me');self.assertIn('--noprofile',args);self.assertIn('--norc',args)
    def test_recovery_focus_rejects_invalid_window_ids_without_x_access(self):
        import recovery_console
        for value in ('','invalid','-1',str(2**40)):
            with patch.dict(os.environ,{'DISPLAY':':99','WINDOWID':value},clear=True),patch.object(recovery_console.ctypes,'CDLL') as library:
                recovery_console.focus_terminal();library.assert_not_called()
    def test_recovery_focus_targets_only_xterm_supplied_window(self):
        import recovery_console
        from unittest.mock import MagicMock
        x=MagicMock();x.XOpenDisplay.return_value=1;x.XSetErrorHandler.return_value=None
        with patch.dict(os.environ,{'DISPLAY':':99','WINDOWID':'42'},clear=True),patch.object(recovery_console.ctypes,'CDLL',return_value=x):recovery_console.focus_terminal()
        x.XSetInputFocus.assert_called_once_with(1,42,1,0);x.XCloseDisplay.assert_called_once_with(1)
    def test_root_and_wayland_launches_rejected(self):
        with patch.object(m.os,'geteuid',return_value=0),self.assertRaises(SystemExit):m.main()
        with patch.object(m.os,'geteuid',return_value=1000),patch.dict(os.environ,{'DISPLAY':':0','WAYLAND_DISPLAY':'wayland-0'},clear=True),self.assertRaises(SystemExit):m.main()
    def test_plain_terminal_bypasses_bad_desktop_and_shell_environment(self):
        env={'DISPLAY':':1','XAUTHORITY':'/tmp/normal-login-cookie','LD_PRELOAD':'bad.so','PYTHONPATH':'bad','BASH_ENV':'bad.sh','ORBIT_SETTINGS_FILE':'bad.json','HOME':'/wrong','PROMPT_COMMAND':'bad','BASH_FUNC_bad%%':'bad','XAPPLRESDIR':'bad'}
        with patch.object(m.os,'geteuid',return_value=1000),patch.object(m.os,'getuid',return_value=1000),patch.object(m.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir='/home/test-user')),patch.object(m.Path,'is_file',return_value=True),patch.dict(os.environ,env,clear=True),patch.object(m.os,'execve') as execute:
            m.main()
        file,args,clean=execute.call_args.args
        self.assertEqual(file,'/usr/bin/xterm');self.assertIn('/usr/lib/abstract/recovery_console.py',args)
        self.assertEqual(clean['HOME'],'/');self.assertEqual(clean['DISPLAY'],':1')
        self.assertEqual(clean['XENVIRONMENT'],'/dev/null');self.assertEqual(clean['INPUTRC'],'/dev/null')
        for name in ('LD_PRELOAD','PYTHONPATH','BASH_ENV','ORBIT_SETTINGS_FILE','PROMPT_COMMAND','BASH_FUNC_bad%%','XAPPLRESDIR'):self.assertNotIn(name,clean)

if __name__=='__main__':unittest.main()

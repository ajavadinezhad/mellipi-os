"""No-seat install/login diagnostics against a synthetic root and inert commands."""
import io,os,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from session import preflight,native_session

class LoginPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.uid=os.getuid();self.calls=[]
        self.env={'PATH':'/fixture/bin','XDG_RUNTIME_DIR':'/run/user/'+str(self.uid)}
        self.runtime=self.root/self.env['XDG_RUNTIME_DIR'].lstrip('/');self.runtime.mkdir(parents=True,mode=0o700)
        self.file('/etc/pam.d/swaylock','auth include login\n');self.file('/usr/share/glvnd/egl_vendor.d/50_fixture.json','{}')
        (self.root/'run/systemd/system').mkdir(parents=True)
        self.system_bus=True;self.user_bus=True;self.logind=True;self.network=True
        self.session='Active=yes\nRemote=no\nType=tty\nClass=user\nSeat=seat0\nVTNr=2\n'
        self.audio='active\nactive\nactive\ninactive\ninactive\n';self.missing=set()
    def tearDown(self):self.temp.cleanup()
    def file(self,name,text):
        target=self.root/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text);return target
    def which(self,name,**kwargs):return None if name in self.missing else '/fixture/bin/'+name
    def runner(self,args,**kwargs):
        self.calls.append((args,kwargs));name=Path(args[0]).name
        if name=='busctl':
            if '--system' in args:
                names=['org.freedesktop.DBus']+(['org.freedesktop.login1'] if self.logind else [])+(['org.freedesktop.NetworkManager'] if self.network else [])
                return SimpleNamespace(returncode=0 if self.system_bus else 1,stdout='as '+str(len(names))+' '+' '.join('"'+name+'"' for name in names))
            return SimpleNamespace(returncode=0 if self.user_bus else 1,stdout='as 1 "org.freedesktop.DBus"')
        if name=='loginctl':return SimpleNamespace(returncode=0,stdout=self.session)
        if name=='systemctl':return SimpleNamespace(returncode=0,stdout=self.audio)
        raise AssertionError('Unapproved command '+str(args))
    def inspect(self,phase='login',**kwargs):
        return preflight.inspect(self.env,phase,root=self.root,which=self.which,runner=self.runner,uid=kwargs.get('uid',self.uid))
    def ids(self,result):return {item['id'] for item in result['findings']}
    def test_install_as_root_needs_no_runtime_seat_or_bus(self):
        self.env.clear();self.runtime.rmdir();result=self.inspect('install',uid=0)
        self.assertTrue(result['ok'],result['issues']);self.assertEqual(self.calls,[])
        self.assertFalse(result['details']['hardware_validated']);self.assertNotIn('user_bus_available',result['details'])
    def test_active_local_tty_and_wayland_logins_are_valid_without_device_chmod(self):
        for kind in ('tty','wayland'):
            self.session=self.session.replace('Type=tty','Type='+kind)
            result=self.inspect();self.assertTrue(result['ok'],result['issues'])
            self.assertTrue(result['details']['active_local_seat'])
            self.assertEqual(result['details']['network']['daemon_status'],'active')
            self.assertEqual(result['details']['audio']['daemon_status'],'active')
            self.assertFalse(result['details']['graphics']['seat_acquired']);self.assertFalse(result['details']['graphics']['egl_initialized'])
        for args,kwargs in self.calls:
            self.assertLessEqual(kwargs['timeout'],3)
            self.assertFalse(any(word in args for word in ('start','restart','enable','SetBrightness','TakeControl')))
    def test_runtime_rejects_relative_missing_symlink_world_access_and_wrong_owner(self):
        self.env['XDG_RUNTIME_DIR']='relative';self.assertIn('runtime',self.ids(self.inspect()))
        self.env['XDG_RUNTIME_DIR']='/run/absent';self.assertIn('runtime',self.ids(self.inspect()))
        self.env['XDG_RUNTIME_DIR']='/run/user/'+str(self.uid)
        self.runtime.chmod(0o750);self.assertIn('runtime',self.ids(self.inspect()))
        self.runtime.chmod(0o700);self.assertIn('runtime',self.ids(self.inspect(uid=self.uid+1)))
        renamed=self.runtime.with_name('private');self.runtime.rename(renamed);self.runtime.symlink_to(renamed,target_is_directory=True)
        self.assertIn('runtime',self.ids(self.inspect()))
    def test_root_and_ssh_inactive_or_seatless_logins_rejected(self):
        self.assertIn('user',self.ids(self.inspect(uid=0)))
        for session in ('Active=yes\nRemote=yes\nSeat=\nVTNr=0\n','Active=no\nRemote=no\nSeat=seat0\nVTNr=2\n','Active=yes\nRemote=no\nSeat=seat0\nVTNr=0\n'):
            self.session=session;self.assertIn('seat',self.ids(self.inspect()))
    def test_missing_buses_logind_and_pam_have_separate_actionable_errors(self):
        self.system_bus=False;self.user_bus=False;(self.root/'etc/pam.d/swaylock').unlink()
        result=self.inspect();self.assertTrue({'system-bus','user-bus','logind','pam'}.issubset(self.ids(result)))
        self.assertFalse(result['ok']);self.assertTrue(all(item['message'] for item in result['findings']))
    def test_missing_optional_services_and_unknown_audio_never_block_desktop(self):
        self.network=False;self.audio='';result=self.inspect()
        self.assertTrue(result['ok'],result['issues']);self.assertEqual(result['details']['network']['daemon_status'],'inactive');self.assertEqual(result['details']['audio']['daemon_status'],'unknown')
        self.assertTrue({'network-daemon','audio-daemon'}.issubset(self.ids(result)))
        self.missing.update(('pactl','nmcli'));result=self.inspect()
        self.assertTrue(result['ok']);self.assertTrue({'network-tool','audio-tool'}.issubset(self.ids(result)))
    def test_alternative_pulse_and_pipewire_session_managers_recognized(self):
        for states in ('inactive\ninactive\ninactive\ninactive\nactive\n','active\nactive\ninactive\nactive\ninactive\n'):
            self.audio=states;self.assertEqual(self.inspect()['details']['audio']['daemon_status'],'active')
    def test_timeout_is_reported_without_retry_or_side_effects(self):
        with patch.object(self,'runner',side_effect=subprocess.TimeoutExpired('fixture',3)):
            result=self.inspect();self.assertFalse(result['ok']);self.assertIn('system-bus',self.ids(result))
    def test_missing_graphics_metadata_is_unverified_not_claimed_as_hardware_test(self):
        (self.root/'usr/share/glvnd/egl_vendor.d/50_fixture.json').unlink()
        result=self.inspect();self.assertTrue(result['ok']);self.assertIn('graphics',self.ids(result));self.assertFalse(result['details']['hardware_validated'])
    def test_missing_supported_login_tools_and_unreadable_pam_block_install(self):
        self.missing.update(('loginctl','busctl','systemctl'))
        with patch.object(preflight.os,'access',return_value=False):result=self.inspect('install')
        self.assertTrue({'loginctl','busctl','systemctl','pam'}.issubset(self.ids(result)));self.assertFalse(result['ok'])

class PreflightIntegrationTest(unittest.TestCase):
    def test_check_login_routes_only_readonly_phase_and_returns_report(self):
        report=dict(ok=True,issues=[],changes_active_session=False)
        with patch.object(native_session.sys,'argv',['native_session.py','--check-login']),patch.object(native_session,'check',return_value=report) as check,patch.object(native_session,'run') as start,patch('sys.stdout',io.StringIO()):
            self.assertEqual(native_session.main(),0);check.assert_called_once_with(login=True);start.assert_not_called()
    def test_default_check_remains_install_safe(self):
        with patch.object(native_session.sys,'argv',['native_session.py','--check']),patch.object(native_session,'check',return_value=dict(ok=True)) as check,patch.object(native_session,'run') as start,patch('sys.stdout',io.StringIO()):
            self.assertEqual(native_session.main(),0);check.assert_called_once_with(login=False);start.assert_not_called()
    def test_real_owner_enforces_login_before_spawning_compositor(self):
        with patch.dict(os.environ,{},clear=True),patch.object(native_session,'check',return_value=dict(ok=False,issues=['Private login required'])) as check,patch.object(native_session.subprocess,'Popen') as start:
            with self.assertRaisesRegex(RuntimeError,'Private login required'):native_session.run()
            check.assert_called_once_with(login=True);start.assert_not_called()

import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from backup_picker import picker_environment,validate_selection

class PickerProtocolTests(unittest.TestCase):
    def test_dialog_uses_ordinary_shell_and_preserves_private_profile(self):
        source={'HOME':'/private/home','XDG_RUNTIME_DIR':'/private/run','XDG_CONFIG_HOME':'/private/config','XDG_DATA_HOME':'/private/data','XDG_STATE_HOME':'/private/state','XDG_CACHE_HOME':'/private/cache','WAYLAND_DISPLAY':'wayland-private','ORBIT_QT':'5','QT_WAYLAND_SHELL_INTEGRATION':'layer-shell','QT_PLUGIN_PATH':'/shell-only','PYTHONPATH':'/shell-only','LD_PRELOAD':'/untrusted','ORBIT_NATIVE_CONTROL':'/private/control','PROVIDER_SECRET':'secret'}
        result=picker_environment(source)
        for k in ('HOME','XDG_RUNTIME_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','WAYLAND_DISPLAY'):self.assertEqual(result[k],source[k])
        self.assertEqual(result['QT_WAYLAND_SHELL_INTEGRATION'],'xdg-shell');self.assertEqual(result['QT_QPA_PLATFORM'],'wayland')
        for k in ('QT_PLUGIN_PATH','PYTHONPATH','LD_PRELOAD','ORBIT_NATIVE_CONTROL','PROVIDER_SECRET'):self.assertNotIn(k,result)
    def test_response_rejects_urls_symlinks_wrong_types_and_excess_selection(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);file=root/'file';file.write_text('text');link=root/'link';link.symlink_to(file)
            invalid=[{'status':'ok','paths':['https://example.test/file']},{'status':'ok','paths':['relative']},{'status':'ok','paths':[str(link)]},{'status':'ok','paths':[str(file)]*129},{'status':'ok','paths':[]},{'status':'error'},{'status':'ok','paths':[str(root)]}]
            for response in invalid:
                with self.subTest(response=response),self.assertRaises(ValueError):validate_selection(response,'files')
            self.assertEqual(validate_selection({'status':'ok','paths':[str(file)]},'files'),[str(file)]);self.assertEqual(validate_selection({'status':'cancelled'},'files'),[])

try:
    from qt_compat import QApplication
    from recovery_tools import RecoveryTools
    HAVE_QT=True
except ImportError:HAVE_QT=False

@unittest.skipUnless(HAVE_QT,'Qt runtime unavailable')
class PickerWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def wait(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.assertTrue(predicate(),'Worker did not finish');self.app.processEvents()
    def test_browse_is_async_and_updates_model_after_validated_result(self):
        with tempfile.TemporaryDirectory() as t:
            calls=[];release=threading.Event();main_thread=threading.get_ident()
            class Process:
                returncode=0
                def communicate(self,timeout=None):release.wait(2);return (json.dumps({'status':'ok','paths':[t]}),None)
                def poll(self):return 0
            def spawn(args,**kwargs):calls.append((args,kwargs,threading.get_ident()));return Process()
            model=RecoveryTools(environment={'HOME':t,'WAYLAND_DISPLAY':'private-wayland','ORBIT_QT':'5','QT_WAYLAND_SHELL_INTEGRATION':'layer-shell'})
            try:
                with patch('recovery_tools.subprocess.Popen',side_effect=spawn):
                    model.chooseDirectory('backupParent');self.assertTrue(model.state['busy']);self.wait(lambda:bool(calls));self.assertNotEqual(calls[0][2],main_thread);self.assertEqual(calls[0][1]['env']['QT_WAYLAND_SHELL_INTEGRATION'],'xdg-shell');self.assertIn('-I',calls[0][0]);self.assertTrue(calls[0][0][2].endswith('/backup_picker.py'));release.set();self.wait(lambda:not model.state['busy']);self.assertEqual(model.state['backupParent'],t);self.assertEqual(model.state['error'],'')
            finally:model.close();release.set()
    def test_cancel_terminates_only_owned_picker_and_preserves_selection(self):
        with tempfile.TemporaryDirectory() as t:
            release=threading.Event();created=[]
            class Process:
                returncode=None;killed=False
                def communicate(self,timeout=None):release.wait(2);return ('',None)
                def poll(self):return self.returncode
                def kill(self):self.killed=True;self.returncode=-9;release.set()
            def spawn(*a,**kw):p=Process();created.append(p);return p
            model=RecoveryTools(environment={'HOME':t,'WAYLAND_DISPLAY':'private-wayland','ORBIT_QT':'5'})
            try:
                with patch('recovery_tools.subprocess.Popen',side_effect=spawn):
                    model.chooseDirectory('backupPath');self.wait(lambda:bool(created));model.cancel();self.wait(lambda:not model.state['busy']);self.assertTrue(created[0].killed);self.assertEqual(model.state['backupPath'],'');self.assertEqual(model.state['error'],'')
            finally:model.close();release.set()
    def test_symlink_pending_marker_is_reported_not_thrown_from_slot(self):
        with tempfile.TemporaryDirectory() as t:
            data=Path(t)/'data';data.mkdir();target=Path(t)/'keep';target.write_text('keep');(data/'pending-settings-restore.json').symlink_to(target);model=RecoveryTools(environment={'HOME':t,'ORBIT_DATA':str(data)})
            try:model.cancelSettings();self.assertIn('Unsafe',model.state['error']);self.assertEqual(target.read_text(),'keep')
            finally:model.close()

if __name__=='__main__':unittest.main()

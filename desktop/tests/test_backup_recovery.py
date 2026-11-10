import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import backup_core as backup
import recovery_packages as recovery

class BackupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name);self.config=self.home/'config';self.data=self.home/'data';self.destination=self.home/'external';self.restore=self.home/'restores'
        for p in (self.config,self.data,self.destination,self.restore):p.mkdir()
        self.env={'HOME':str(self.home),'ORBIT_SETTINGS_FILE':str(self.config/'settings.json'),'ORBIT_DATA':str(self.data),'XDG_STATE_HOME':str(self.home/'state')}
        (self.config/'settings.json').write_text('{"mode":"dark"}');(self.data/'outputs-native.json').write_text('{"HDMI-A-1":{"scale":1}}')
    def create(self,personal=()):return Path(backup.create_backup(self.destination,self.env,personal)['path'])
    def edit_manifest(self,path,mutate):
        p=path/'manifest.json';v=json.loads(p.read_text());mutate(v);p.write_text(json.dumps(v))
    def test_explicit_personal_selection_and_no_overwrite_restore(self):
        docs=self.home/'Documents';docs.mkdir();(docs/'same.txt').write_text('important');(docs/'nested').mkdir();(docs/'nested/child').write_text('nested')
        unrelated=self.home/'not-selected';unrelated.write_text('private');b=self.create([docs]);manifest=backup.inspect_backup(b)
        self.assertEqual(sum(r.get('type','file')=='file' for r in manifest['files']),4);self.assertFalse(any('not-selected' in r['path'] for r in manifest['files']))
        (self.restore/'same.txt').write_text('keep');result=Path(backup.restore_files(b,self.restore)['path']);self.assertEqual((result/'personal/0000/Documents/same.txt').read_text(),'important');self.assertEqual((self.restore/'same.txt').read_text(),'keep')
        self.assertNotEqual(Path(backup.restore_files(b,self.restore)['path']),result)
        self.assertEqual(result.stat().st_mode&0o777,0o700)
    def test_nested_backup_destination_is_rejected(self):
        with self.assertRaises(ValueError):backup.create_backup(self.destination,self.env,[self.home])
        self.assertEqual(list(self.destination.iterdir()),[])
        nested=self.home/'nested';nested.mkdir()
        with self.assertRaises(ValueError):backup.create_backup(self.destination,self.env,[nested/'..'])
    def test_symlinks_and_special_files_are_not_followed(self):
        docs=self.home/'Documents';docs.mkdir();(docs/'link').symlink_to(self.config/'settings.json')
        with self.assertRaises(ValueError):self.create([docs])
        self.assertEqual(list(self.destination.iterdir()),[])
        (docs/'link').unlink();os.mkfifo(docs/'pipe')
        with self.assertRaises(ValueError):self.create([docs])
    def test_manifest_and_intermediate_directory_symlink_rejected(self):
        b=self.create();original=b/'manifest.json';saved=b/'saved.json';original.rename(saved);original.symlink_to(saved)
        with self.assertRaises(ValueError):backup.inspect_backup(b)
        alias=self.home/'external-alias';alias.symlink_to(self.destination,target_is_directory=True)
        with self.assertRaises(ValueError):backup.create_backup(alias,self.env)
    def test_corruption_detected_before_any_restore_files_are_created(self):
        b=self.create();(b/'files/settings/config/settings.json').write_text('corrupt')
        with self.assertRaises(ValueError):backup.restore_files(b,self.restore)
        self.assertEqual(list(self.restore.iterdir()),[])
    def test_traversal_duplicate_and_unknown_settings_rejected(self):
        for name in ('../../escape','/absolute','settings/config/../../escape','settings/config/not-allowed.json'):
            b=self.create();self.edit_manifest(b,lambda v:v['files'][0].update(path=name))
            with self.subTest(name=name),self.assertRaises(ValueError):backup.inspect_backup(b)
        b=self.create();self.edit_manifest(b,lambda v:v['files'].append(v['files'][0]))
        with self.assertRaises(ValueError):backup.inspect_backup(b)
    def test_cancelled_backup_cleans_incomplete_directory(self):
        with self.assertRaises(InterruptedError):backup.create_backup(self.destination,self.env,cancelled=lambda:True)
        self.assertEqual(list(self.destination.iterdir()),[])
    def test_verification_and_restore_can_be_cancelled(self):
        b=self.create()
        with self.assertRaises(InterruptedError):backup.inspect_backup(b,cancelled=lambda:True)
        with self.assertRaises(InterruptedError):backup.restore_files(b,self.restore,cancelled=lambda:True)
        self.assertEqual(list(self.restore.iterdir()),[])
    def test_queued_restore_preserves_current_copy_and_newer_edits(self):
        b=self.create();settings=self.config/'settings.json';settings.write_text('{"mode":"light"}');backup.queue_settings_restore(b,self.env)
        outputs=self.data/'outputs-native.json';outputs.write_text('{"new":"edit"}')
        result=backup.consume_settings_restore(self.env);self.assertIn('config/settings.json',result['restored']);self.assertIn('data/outputs-native.json',result['preserved']);self.assertEqual(json.loads(settings.read_text()),{'mode':'dark'});self.assertEqual(json.loads(outputs.read_text()),{'new':'edit'})
        before=list(self.data.glob('before-settings-restore-*/config/settings.json'));self.assertEqual(len(before),1);self.assertEqual(json.loads(before[0].read_text()),{'mode':'light'});self.assertFalse((self.data/'pending-settings-restore.json').exists())
    def test_queue_is_explicit_and_cannot_silently_replace_pending_request(self):
        b=self.create();backup.queue_settings_restore(b,self.env)
        with self.assertRaises(FileExistsError):backup.queue_settings_restore(b,self.env)
    def test_malformed_pending_request_changes_no_settings(self):
        b=self.create();backup.queue_settings_restore(b,self.env);p=self.data/'pending-settings-restore.json';v=json.loads(p.read_text());v['desired']['../escape']='{}';v['expected']['../escape']=None;p.write_text(json.dumps(v));original=(self.config/'settings.json').read_bytes()
        with self.assertRaises(ValueError):backup.consume_settings_restore(self.env)
        self.assertEqual((self.config/'settings.json').read_bytes(),original);self.assertFalse((self.home/'escape').exists())
    def test_settings_target_symlink_is_never_replaced(self):
        b=self.create();backup.queue_settings_restore(b,self.env);target=self.config/'settings.json';target.unlink();outside=self.home/'keep';outside.write_text('keep');target.symlink_to(outside)
        with self.assertRaises(ValueError):backup.consume_settings_restore(self.env)
        self.assertEqual(outside.read_text(),'keep');self.assertTrue(target.is_symlink())
    def test_custom_settings_filename_preserved(self):
        custom=self.config/'custom.json';custom.write_text('{"mode":"black"}');self.env['ORBIT_SETTINGS_FILE']=str(custom);b=self.create();self.assertEqual(json.loads((b/'files/settings/config/settings.json').read_text()),{'mode':'black'})
    def test_empty_folders_execute_bit_and_modification_times_round_trip(self):
        docs=self.home/'Project';docs.mkdir();empty=docs/'empty';empty.mkdir();nested=docs/'nested';nested.mkdir();child= nested/'deep-empty';child.mkdir();script=docs/'run.sh';script.write_text('#!/bin/sh\necho example\n');script.chmod(0o6755);plain=docs/'notes';plain.write_text('text');plain.chmod(0o666)
        stamp=1_000_000_001_234_567_890
        for index,p in enumerate((script,plain,empty,child,nested,docs)):os.utime(p,ns=(stamp+index,stamp+index))
        expected={str(p.relative_to(docs)):p.stat().st_mtime_ns for p in (script,plain,empty,child,nested,docs)}
        b=self.create([docs]);self.assertEqual(backup.inspect_backup(b)['version'],2);result=Path(backup.restore_files(b,self.restore)['path'])/'personal/0000/Project'
        self.assertTrue((result/'empty').is_dir());self.assertEqual(list((result/'empty').iterdir()),[]);self.assertTrue((result/'nested/deep-empty').is_dir());self.assertEqual((result/'run.sh').stat().st_mode&0o7777,0o700);self.assertEqual((result/'notes').stat().st_mode&0o7777,0o600)
        for name,mtime in expected.items():self.assertEqual((result/name).stat().st_mtime_ns,mtime,name)
    def test_version_one_backup_remains_readable_without_fabricated_metadata(self):
        script=self.home/'old.sh';script.write_text('echo old');script.chmod(0o700);b=self.create([script]);p=b/'manifest.json';v=json.loads(p.read_text());v['version']=1
        for row in v['files']:
            for key in ('type','mode','mtime_ns'):row.pop(key,None)
        p.write_text(json.dumps(v));result=Path(backup.restore_files(b,self.restore)['path'])/'personal/0000/old.sh';self.assertEqual(result.read_text(),'echo old');self.assertEqual(result.stat().st_mode&0o7777,0o600)
    def test_unsafe_permission_and_timestamp_records_fail_before_restore(self):
        for mode,mtime in ((0o4755,0),(0o777,0),(0o700,False),(0o600,2**100)):
            b=self.create();self.edit_manifest(b,lambda v:v['files'][0].update(mode=mode,mtime_ns=mtime))
            with self.subTest(mode=mode,mtime=mtime),self.assertRaises(ValueError):backup.restore_files(b,self.restore)
            self.assertEqual(list(self.restore.iterdir()),[])
    def test_only_empty_personal_folder_can_be_restored_without_settings(self):
        for p in (self.config/'settings.json',self.data/'outputs-native.json'):p.unlink()
        empty=self.home/'Empty';empty.mkdir();b=self.create([empty]);v=backup.inspect_backup(b);self.assertEqual(len(v['files']),1);result=backup.restore_files(b,self.restore);self.assertEqual(result['files'],0);self.assertEqual(result['directories'],1);self.assertTrue((Path(result['path'])/'personal/0000/Empty').is_dir())

class PackageRecoveryTests(unittest.TestCase):
    def test_root_recovery_does_not_forward_apt_or_dpkg_overrides(self):
        env=recovery.recovery_environment({'APT_CONFIG':'/tmp/evil','DPKG_ROOT':'/tmp/other','DISPLAY':':0','DBUS_SESSION_BUS_ADDRESS':'private','PATH':'/tmp','TERM':'xterm-256color'})
        self.assertEqual(set(env),{'PATH','HOME','USER','LOGNAME','LANG','TERM'});self.assertEqual(env['PATH'],'/usr/sbin:/usr/bin:/sbin:/bin')
    def test_only_known_signed_apt_package_specs_allowed(self):
        for spec in (['bash=1'],['mellipi-shell=--allow-unauthenticated'],['/tmp/a.deb=1'],['mellipi-shell=1;echo pwn'],['mellipi-shell=1','mellipi-shell=2'],['mellipi-desktop=1']):
            with self.subTest(spec=spec),self.assertRaises(ValueError):recovery.restore_command(spec)
        self.assertEqual(recovery.restore_command(['mellipi-shell=0.1.8','abstract-shell=0.1.8']),['/usr/bin/apt-get','--allow-downgrades','install','mellipi-shell=0.1.8','abstract-shell=0.1.8'])
    def test_save_working_version_records_transitional_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            env={'HOME':temporary}
            def run(cmd,**kw):return SimpleNamespace(returncode=0 if cmd[-1] in ('mellipi-shell','abstract-shell') else 1,stdout='installed\t0.1.8')
            result=recovery.save_checkpoint(env,run);self.assertEqual(result['packages'],['mellipi-shell=0.1.8','abstract-shell=0.1.8']);self.assertIn('sudo mellipi-recover --restore',result['command']);self.assertEqual(recovery.checkpoint_path(env).stat().st_mode&0o777,0o600)
    def test_corrupt_or_world_readable_checkpoint_is_not_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            env={'HOME':temporary};path=recovery.checkpoint_path(env);path.parent.mkdir(parents=True);path.write_text('{"version":1,"packages":["bash=1"]}');path.chmod(0o600)
            with self.assertRaises(ValueError):recovery.load_checkpoint(env)
            path.write_text('{"version":1,"packages":["mellipi-shell=0.1.8"]}');path.chmod(0o644)
            with self.assertRaises(ValueError):recovery.load_checkpoint(env)

if __name__=='__main__':unittest.main()

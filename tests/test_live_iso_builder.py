"""Safety and installer defaults; no mounts, chroots, disks or host services."""
import hashlib,importlib.util,json,stat,tempfile,unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock
try:
 import yaml
except ImportError:yaml=None
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('live_iso_builder',ROOT/'tools/build-live-iso.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class BuildBoundaryTest(unittest.TestCase):
 def test_unprivileged_invocation_stops_before_any_directory_creation(self):
  with mock.patch.object(builder.os,'geteuid',return_value=1000),mock.patch.object(Path,'mkdir') as mkdir:
   with self.assertRaisesRegex(SystemExit,'disposable Mellipi build VM'):builder.guard('/home/abstract/abstract-iso/build')
   mkdir.assert_not_called()
 def test_root_on_another_host_cannot_start_build(self):
  with mock.patch.object(builder.os,'geteuid',return_value=0),mock.patch.object(Path,'read_text',return_value='workstation\n'),mock.patch.object(Path,'mkdir') as mkdir,mock.patch.object(builder.subprocess,'check_output') as command:
   with self.assertRaisesRegex(SystemExit,'named disposable QA guest'):builder.guard('/home/abstract/abstract-iso/build')
   mkdir.assert_not_called();command.assert_not_called()
 def test_marker_without_qemu_cannot_start_build(self):
  with mock.patch.object(builder.os,'geteuid',return_value=0),mock.patch.object(Path,'read_text',return_value='abstract-qa\n'),mock.patch.object(Path,'is_file',return_value=True),mock.patch.object(builder.subprocess,'check_output',return_value='none\n'),mock.patch.object(Path,'mkdir') as mkdir:
   with self.assertRaisesRegex(SystemExit,'QEMU/KVM guest'):builder.guard('/home/abstract/abstract-iso/build')
   mkdir.assert_not_called()

class CalamaresModuleInputTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='abstract-module-input-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'root';self.root.mkdir()
  header=bytearray(64);header[:6]=b'\x7fELF\x02\x01';header[18:20]=bytes((62,0))
  self.module=Path(self.temp.name)/'partition.so';self.module.write_bytes(header+b'new module fixture');self.digest=builder.file_sha256(self.module)
  self.target=self.root/builder.CALAMARES_PARTITION_PATH;self.target.parent.mkdir(parents=True);self.target.write_bytes(header+b'original fixture');self.original=self.target.read_bytes()
  self.metadata=Path(self.temp.name)/'provenance.json'
  self.provenance={'module_sha256':self.digest,'module_bytes':self.module.stat().st_size,'ubuntu_package':builder.CALAMARES_VERSION,'geometry_regression':{'GPT_last_usable':50331614,'MSDOS_last_usable':50331647,'default_encryption_only':False},'patches':{name:'a'*64 for name in ('enable-only-present-with-encryption-partitions.patch','calamares-gpt-usable-boundary.patch','calamares-default-encryption-flag.patch')}}
  self.metadata.write_text(json.dumps(self.provenance));self.args=SimpleNamespace(calamares_partition_module=self.module,calamares_partition_sha256=self.digest,calamares_partition_provenance=self.metadata)
 def test_reviewed_module_is_applied_only_to_the_pinned_abi_and_is_idempotent(self):
  with mock.patch.object(builder,'CALAMARES_STOCK_MODULE_SHA256',builder.file_sha256(self.target)),mock.patch.object(builder,'chroot',return_value=SimpleNamespace(stdout=builder.CALAMARES_VERSION)):
   for _ in range(2):self.assertEqual(builder.apply_calamares_partition_module(self.root,self.args)['module_sha256'],self.digest)
  self.assertEqual(self.target.read_bytes(),self.module.read_bytes())
 def test_wrong_sha_or_regression_proof_stops_before_any_chroot_or_copy(self):
  for kind in ('sha','geometry'):
   self.args.calamares_partition_sha256='0'*64 if kind=='sha' else self.digest
   self.provenance['geometry_regression']['default_encryption_only']=kind=='geometry';self.metadata.write_text(json.dumps(self.provenance))
   with mock.patch.object(builder,'chroot') as command,self.assertRaises(ValueError):builder.apply_calamares_partition_module(self.root,self.args)
   command.assert_not_called();self.assertEqual(self.target.read_bytes(),self.original)
 def test_unknown_stock_module_or_wrong_package_abi_cannot_be_overwritten(self):
  for version in (builder.CALAMARES_VERSION,'another ABI'):
   with mock.patch.object(builder,'chroot',return_value=SimpleNamespace(stdout=version)),self.assertRaises(ValueError):builder.apply_calamares_partition_module(self.root,self.args)
   self.assertEqual(self.target.read_bytes(),self.original)
 def test_image_without_validated_module_inputs_is_refused(self):
  self.args.calamares_partition_module=None
  with self.assertRaisesRegex(SystemExit,'validated Calamares'):builder.apply_calamares_partition_module(self.root,self.args)

@unittest.skipIf(yaml is None,'PyYAML is required to validate installer configuration')
class InstallerDefaultsTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='abstract-iso-defaults-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  theme = self.root/'usr/lib/abstract/themes/forest.json'
  theme.parent.mkdir(parents=True)
  self.theme=json.loads((ROOT/'desktop/themes/forest.json').read_text())
  self.theme['accent']='#a8cf94'
  theme.write_text(json.dumps(self.theme))
  builder.configure_installer(self.root,'0.1.6');builder.configure_live(self.root,'0.1.6')
 def module(self,name):return yaml.safe_load((self.root/'etc/calamares/modules'/name).read_text())
 def test_partitioning_requires_explicit_choice_and_final_confirmation(self):
  settings=yaml.safe_load((self.root/'etc/calamares/settings.conf').read_text())
  self.assertIs(settings['prompt-install'],True);self.assertIs(settings['dont-chroot'],False)
  self.assertEqual(self.module('partition.conf')['initialPartitioningChoice'],'none')
  self.assertIs(self.module('users.conf')['doAutologin'],False)
  self.assertEqual(self.module('partition.conf')['partitionLayout'],[{'name':'rootfs','filesystem':'ext4','mountPoint':'/','size':'100%','minSize':'12G'}])
 def test_copy_refuses_live_overlay_and_requires_a_mounted_target_partition(self):
  settings=yaml.safe_load((self.root/'etc/calamares/settings.conf').read_text());jobs=next(item['exec'] for item in settings['sequence'] if 'exec' in item)
  self.assertLess(jobs.index('mount'),jobs.index('shellprocess@abstracttargetcheck'));self.assertLess(jobs.index('shellprocess@abstracttargetcheck'),jobs.index('unpackfs'))
  helper={'__name__':'abstract_target_check_test'}
  exec(compile((self.root/'usr/lib/abstract/iso-check-target').read_text(),'iso-check-target','exec'),helper)
  for fstype,source in [('tmpfs','tmpfs'),('overlay','overlay')]:
   result={'filesystems':[{'target':str(self.root),'fstype':fstype,'source':source}]}
   with mock.patch.object(helper['subprocess'],'check_output',return_value=json.dumps(result)),self.assertRaises(ValueError):helper['check_target'](self.root)
  result={'filesystems':[{'target':str(self.root),'fstype':'ext4','source':'/dev/qa-target'}]}
  with mock.patch.object(helper['subprocess'],'check_output',return_value=json.dumps(result)),mock.patch.object(Path,'resolve',return_value=self.root),mock.patch.object(helper['os'],'stat',return_value=SimpleNamespace(st_mode=stat.S_IFBLK)):
   helper['check_target'](self.root)
 def test_install_is_offline_and_uses_the_iso_filesystem(self):
  unpack=self.module('unpackfs.conf')['unpack'];self.assertEqual(unpack,[{'source':'/cdrom/casper/filesystem.squashfs','sourcefs':'squashfs','destination':''}])
  packages=self.module('packages.conf');self.assertIs(packages['update_db'],False);self.assertIs(packages['update_system'],False)
  self.assertEqual(packages['operations'],[{'remove':['casper','calamares']}])
 def test_live_lock_override_does_not_disable_installed_lock_defaults(self):
  prefs=json.loads((self.root/'etc/skel/.config/abstract/settings.json').read_text());self.assertNotIn('idleLockEnabled',prefs);self.assertNotIn('lockBeforeSleep',prefs)
  self.assertIn('mellipi-terminal.desktop',prefs['pins'])
  self.assertIn('mellipi-files.desktop',prefs['pins'])
  self.assertEqual(prefs['wallpaper'],'theme-forest')
  self.assertEqual(prefs['accent'],self.theme['accent'])
  hook=(self.root/'usr/share/initramfs-tools/scripts/casper-bottom/99mellipi-live').read_text();self.assertIn('"idleLockEnabled": false',hook);self.assertIn('"lockBeforeSleep": false',hook)
  self.assertIn('Locking is unavailable in the password-free live session.',hook)
  cleanup=(self.root/'usr/lib/abstract/iso-target-cleanup').read_text();self.assertIn('casper-bottom/99mellipi-live',cleanup)
  self.assertFalse((self.root/'home/abstract').exists())
 def test_target_mounts_and_uuid_settings_are_present(self):
  mounts=self.module('mount.conf')['extraMounts'];self.assertTrue({'/proc','/sys','/dev','/run','/run/udev','/sys/firmware/efi/efivars'}.issubset({m['mountPoint'] for m in mounts}))
  self.assertIn('default',self.module('fstab.conf')['tmpOptions'])
  self.assertEqual((self.root/'etc/initramfs-tools/conf.d/mellipi-live').read_text(),'export CASPER_GENERATE_UUID=1\n')
 def test_required_branding_slideshow_and_images_resolve(self):
  directory=self.root/'etc/calamares/branding/abstract';branding=yaml.safe_load((directory/'branding.desc').read_text())
  self.assertEqual(branding['slideshow'],['abstract.svg'])
  for name in [*branding['slideshow'],*branding['images'].values()]:self.assertTrue((directory/name).is_file(),name)
  style=(directory/'stylesheet.qss').read_text()
  forest=self.theme
  self.assertEqual(branding['style']['SidebarBackgroundCurrent'],forest['accent'])
  self.assertFalse(branding['welcomeExpandingLogo'])
  self.assertIn(forest['accent'],(directory/branding['images']['productWelcome']).read_text())
  for color in ('background','surface','raised','text'):
   self.assertIn(forest['palette'][color],style)
  self.assertIn('QPushButton:focus',style)
  self.assertIn('QPushButton#view-button-next:enabled',style)
  self.assertIn('QProgressBar::chunk',style)
 def test_installer_entry_has_no_unattended_partition_command(self):
  entry=(self.root/'usr/share/applications/mellipi-install.desktop').read_text();self.assertIn('Exec=/usr/bin/mellipi-install',entry)
  launcher=(self.root/'usr/bin/mellipi-install').read_text();self.assertIn('boot=casper',launcher);self.assertIn('/usr/lib/abstract/iso-installer-root',launcher)
  self.assertNotIn('mkfs',launcher);self.assertNotIn('parted',launcher)
 def installer_helper(self):
  namespace={'__name__':'abstract_installer_helper_test'}
  exec(compile((self.root/'usr/lib/abstract/iso-installer-root').read_text(),'iso-installer-root','exec'),namespace)
  return namespace
 def test_privileged_installer_accepts_only_the_callers_private_display_socket(self):
  helper=self.installer_helper();directory=SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=1000);socket=SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=1000)
  with mock.patch.object(Path,'lstat',side_effect=[directory,socket]):
   self.assertEqual(helper['display_socket']('/run/user/1000','wayland-1',1000),'/run/user/1000/wayland-1')
  for runtime,display,uid in [('/run/user/1001','wayland-1',1000),('/run/user/1000','../wayland-1',1000),('/run/user/1000','/tmp/display',1000),('/run/user/0','wayland-1',0)]:
   with mock.patch.object(Path,'lstat',return_value=directory),self.assertRaises(ValueError):helper['display_socket'](runtime,display,uid)
  for bad in [SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=1000),SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=1001)]:
   with mock.patch.object(Path,'lstat',side_effect=[directory,bad]),self.assertRaises(ValueError):helper['display_socket']('/run/user/1000','wayland-1',1000)
 def test_installer_helper_refuses_an_ordinary_host_before_creating_root_state(self):
  helper=self.installer_helper()
  with mock.patch.object(helper['os'],'geteuid',return_value=0),mock.patch.object(helper['sys'],'argv',['iso-installer-root','/run/user/1000','wayland-1']),mock.patch.object(Path,'read_text',return_value='quiet'),mock.patch.object(helper['tempfile'],'TemporaryDirectory') as temporary:
   with self.assertRaisesRegex(SystemExit,'live desktop'):helper['main']()
   temporary.assert_not_called()

if __name__=='__main__':unittest.main()

"""Security gates; no firmware, disk, bootloader install or host changes."""
import importlib.util,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
secure=load('secure_boot_image_test','secure-boot-image.py')
builder=load('secure_boot_installer_test','build-live-iso.py')

class SignedImageGates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.source=self.base/'source.iso';self.source.write_bytes(b'preserved original ISO');self.out=self.base/'candidate.iso';self.root=self.base/'root';self.work=self.base/'work';self.work.mkdir()
        for path in ('usr/lib/shim/shimx64.efi.signed','usr/lib/shim/mmx64.efi','usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed'):
            p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'MZfixture')
    def test_existing_candidate_and_symlink_source_are_never_overwritten(self):
        self.out.write_bytes(b'keep')
        with mock.patch.object(secure,'run') as run,self.assertRaises(ValueError):secure.build(self.source,self.out,self.root,self.work)
        run.assert_not_called();self.assertEqual(self.out.read_bytes(),b'keep')
        self.out.unlink();link=self.base/'source-link.iso';link.symlink_to(self.source)
        with mock.patch.object(secure,'run') as run,self.assertRaises(ValueError):secure.build(link,self.out,self.root,self.work)
        run.assert_not_called();self.assertEqual(self.source.read_bytes(),b'preserved original ISO')
    def test_unsigned_efi_stops_before_any_filesystem_image_or_iso_write(self):
        with mock.patch.object(secure,'run',return_value=SimpleNamespace(stdout='No signature table present')) as run,self.assertRaisesRegex(ValueError,'Unsigned EFI'):
            secure.build(self.source,self.out,self.root,self.work)
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0][0],'sbverify');self.assertFalse(self.out.exists());self.assertEqual(list(self.work.iterdir()),[])
    def test_unsigned_kernel_stops_before_fat_or_boot_partition_creation(self):
        def command(args,**kwargs):
            if args[0]=='xorriso':Path(args[-1]).write_bytes(b'unsigned kernel');return SimpleNamespace(stdout='')
            if str(args[-1]).endswith('kernel'):return SimpleNamespace(stdout='No signature table present')
            return SimpleNamespace(stdout='signature 1\n')
        with mock.patch.object(secure,'run',side_effect=command) as run,self.assertRaisesRegex(ValueError,'kernel lacks'):
            secure.build(self.source,self.out,self.root,self.work)
        self.assertFalse(any(c.args[0][0] in ('mkfs.vfat','mcopy') for c in run.call_args_list));self.assertFalse(self.out.exists());self.assertFalse((self.work/'signed-efi.img').exists())
    def test_missing_signed_package_stops_early(self):
        (self.root/'usr/lib/shim/mmx64.efi').unlink()
        with mock.patch.object(secure,'run',return_value=SimpleNamespace(stdout='signature 1')) as run,self.assertRaisesRegex(ValueError,'Missing signed'):
            secure.build(self.source,self.out,self.root,self.work)
        self.assertFalse(self.out.exists())

class SignedInstallerGates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        theme = self.root/'usr/lib/abstract/themes/forest.json'
        theme.parent.mkdir(parents=True)
        theme.write_bytes((ROOT/'desktop/themes/forest.json').read_bytes())
        builder.configure_installer(self.root,'0.1.9')
        self.helper={'__name__':'secure_installer_unit_test'};exec(compile((self.root/'usr/lib/abstract/iso-grub-install').read_text(),'iso-grub-install','exec'),self.helper)
        self.arguments=['--target=x86_64-efi','--efi-directory=/boot/efi','--bootloader-id=ubuntu','--force']
    def test_uefi_plan_demands_signed_install_and_removes_force(self):
        command,device=self.helper['plan'](self.arguments);self.assertIsNone(device);self.assertIn('--uefi-secure-boot',command);self.assertNotIn('--force',command)
        for extra in ('--no-uefi-secure-boot','--bootloader-id=other','--efi-directory=/tmp/target'):
            with self.assertRaises(ValueError):self.helper['plan']([*self.arguments,extra])
    def test_bios_plan_preserves_only_selected_standard_disk_install(self):
        command,device=self.helper['plan'](['--target=i386-pc','--recheck','--force','/dev/vda']);self.assertEqual(device,'/dev/vda');self.assertNotIn('--uefi-secure-boot',command)
        for args in (['--target=i386-pc','/tmp/file'],['--target=i386-pc','/dev/../etc/file'],['--target=i386-pc','/dev/vda','/dev/vdb'],['--target=i386-pc','--directory=/tmp','/dev/vda']):
            with self.assertRaises(ValueError):self.helper['plan'](args)
    def test_signed_install_cannot_run_unprivileged_or_without_mounted_esp(self):
        with mock.patch.object(self.helper['os'],'geteuid',return_value=1000),mock.patch.object(self.helper['subprocess'],'run') as run,self.assertRaises(SystemExit):self.helper['main']()
        run.assert_not_called()
        with mock.patch.object(self.helper['os'],'geteuid',return_value=0),mock.patch.object(self.helper['sys'],'argv',['iso-grub-install',*self.arguments]),mock.patch.object(Path,'is_file',return_value=True),mock.patch.object(Path,'is_symlink',return_value=False),mock.patch.object(self.helper['os'].path,'ismount',return_value=False),mock.patch.object(self.helper['subprocess'],'run') as run,self.assertRaisesRegex(ValueError,'not mounted'):
            self.helper['main']()
        run.assert_not_called()
    def test_live_root_contains_distribution_signed_boot_packages(self):
        self.assertTrue({'grub-efi-amd64-signed','shim-signed','mokutil','sbsigntool'}.issubset(builder.BASE_PACKAGES))
        config=(self.root/'etc/calamares/modules/bootloader.conf').read_text();self.assertIn('efiBootloaderId: ubuntu',config);self.assertIn('installEFIFallback: false',config);self.assertIn('grubInstall: /usr/lib/abstract/iso-grub-install',config)
    def test_install_only_helper_is_removed_after_bootloader_job(self):
        try:import yaml
        except ImportError:self.skipTest('PyYAML is required for installer configuration checks')
        settings=yaml.safe_load((self.root/'etc/calamares/settings.conf').read_text());jobs=next(row['exec'] for row in settings['sequence'] if 'exec' in row)
        self.assertLess(jobs.index('bootloader'),jobs.index('shellprocess@abstractbootcleanup'));self.assertLess(jobs.index('shellprocess@abstractbootcleanup'),jobs.index('umount'))
        cleanup=yaml.safe_load((self.root/'etc/calamares/modules/abstractbootcleanup.conf').read_text());self.assertIs(cleanup['dontChroot'],False);self.assertEqual(cleanup['script'],['/usr/bin/rm -f /usr/lib/abstract/iso-grub-install'])

if __name__=='__main__':unittest.main()

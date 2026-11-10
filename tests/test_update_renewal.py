"""Renewal against real disposable signatures and packages; never live state."""
import importlib.util,json,shutil,subprocess,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
renewal=load('test_renewal','renew-update-repository.py');apt=load('test_renewal_apt','build-apt-repository.py');publication=load('test_renewal_publication','prepare-public-release.py')

@unittest.skipUnless(all(shutil.which(n) for n in ['gpg','gpgv','gpgconf','dpkg-deb','dpkg-scanpackages']),'GPG and Debian tools required')
class UpdateRenewalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='mellipi-renewal-tests-');cls.base=Path(cls.temp.name);cls.home=cls.base/'signer';cls.home.mkdir(mode=0o700)
        subprocess.run(['gpg','--homedir',str(cls.home),'--batch','--pinentry-mode','loopback','--passphrase','','--quick-generate-key','Renewal Test <test@example.invalid>','ed25519','sign','0'],capture_output=True,check=True)
        rows=subprocess.check_output(['gpg','--homedir',str(cls.home),'--batch','--with-colons','--list-keys'],text=True);cls.key=next(r.split(':')[9] for r in rows.splitlines() if r.startswith('fpr:'))
    @classmethod
    def tearDownClass(cls):
        subprocess.run(['gpgconf','--homedir',str(cls.home),'--kill','gpg-agent'],capture_output=True);cls.temp.cleanup()
    def setUp(self):
        self.tempdir=tempfile.TemporaryDirectory(dir=self.base);self.addCleanup(self.tempdir.cleanup);self.work=Path(self.tempdir.name);self.public=self.work/'public';self.public.mkdir()
        stage=self.work/'package';(stage/'DEBIAN').mkdir(parents=True);(stage/'DEBIAN/control').write_text('Package: mellipi-fixture\nVersion: 1.0\nArchitecture: all\nMaintainer: Test <test@example.invalid>\nDescription: renewal fixture\n');(stage/'payload').write_text('unchanged package')
        self.package=self.work/'fixture.deb';subprocess.run(['dpkg-deb','--build','--root-owner-group',str(stage),str(self.package)],check=True,capture_output=True)
    def prepare(self,origin='Mellipi'):
        apt.build(self.public/'apt',[self.package],self.home,self.key,valid_days=1,now=datetime(2020,1,1,tzinfo=timezone.utc),origin=origin)
        (self.public/'apt/install-update-source.sh').write_text('#!/bin/sh\nprintf original-helper\n');(self.public/'apt/install-update-source.sh').chmod(0o755)
        (self.public/'index.html').write_text('unchanged website');(self.public/'sources').mkdir();(self.public/'sources/fixture-source.tar.gz').write_bytes(b'unchanged corresponding source');self.manifest()
    def manifest(self):
        value={'release':'1.0','signing_fingerprint':self.key,'sources':['sources/fixture-source.tar.gz'],'files':publication.records(self.public)};(self.public/'publication-manifest.json').write_text(json.dumps(value,indent=2)+'\n')
    def snapshot(self):return {str(p.relative_to(self.public)):p.read_bytes() for p in self.public.rglob('*') if p.is_file()}
    def test_expired_release_renews_but_keeps_payload_sources_helper_and_old_hashes(self):
        self.prepare();before=self.snapshot();hashes={p.name for p in (self.public/'apt').glob('dists/noble/main/binary-amd64/by-hash/SHA256/*')}
        with self.assertRaisesRegex(ValueError,'expired'):publication.validate_existing(self.public)
        result=renewal.renew(self.public,self.home,self.key);self.assertTrue(result['metadata_renewed']);self.assertFalse(result['uploaded']);self.assertFalse(result['host_apt_changed'])
        after=self.snapshot()
        for name,value in before.items():
            if name.startswith(('sources/','apt/pool/')) or name in ['index.html','apt/install-update-source.sh']:self.assertEqual(after[name],value,name)
        self.assertTrue(hashes<={p.name for p in (self.public/'apt').glob('dists/noble/main/binary-amd64/by-hash/SHA256/*')});publication.validate_existing(self.public)
    def test_legacy_origin_preserved_so_existing_apt_clients_do_not_need_reapproval(self):
        self.prepare('Abstract');renewal.renew(self.public,self.home,self.key);text=(self.public/'apt/dists/noble/Release').read_text();self.assertIn('Origin: Abstract\nLabel: Abstract\n',text)
    def test_tampered_payload_or_signed_metadata_does_not_modify_publication(self):
        self.prepare();package=next((self.public/'apt/pool').rglob('*.deb'));package.write_bytes(package.read_bytes()+b'tampered');self.manifest();before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'mismatch'):renewal.renew(self.public,self.home,self.key)
        self.assertEqual(before,self.snapshot())
        package.write_bytes(self.package.read_bytes());signed=self.public/'apt/dists/noble/InRelease';signed.write_bytes(signed.read_bytes().replace(b'Origin: Mellipi',b'Origin: Invalid'));self.manifest();before=self.snapshot()
        with self.assertRaises(subprocess.CalledProcessError):renewal.renew(self.public,self.home,self.key)
        self.assertEqual(before,self.snapshot())
    def test_late_validation_failure_leaves_entire_original_publication_unchanged(self):
        self.prepare();before=self.snapshot()
        def modules(name,file):return publication if file=='prepare-public-release.py' else apt
        with patch.object(renewal,'module',side_effect=modules),patch.object(publication,'validate_existing',side_effect=ValueError('injected late validation failure')):
            with self.assertRaisesRegex(ValueError,'injected late'):renewal.renew(self.public,self.home,self.key)
        self.assertEqual(before,self.snapshot())
    def test_manifest_mismatch_symlink_and_published_signer_are_rejected(self):
        self.prepare();(self.public/'index.html').write_text('changed');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'manifest'):renewal.renew(self.public,self.home,self.key)
        self.assertEqual(before,self.snapshot())
        with self.assertRaisesRegex(ValueError,'outside'):renewal.renew(self.public,self.public/'private-signing-key',self.key)
        alias=self.work/'alias';alias.symlink_to(self.public,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):renewal.renew(alias,self.home,self.key)

if __name__=='__main__':unittest.main()

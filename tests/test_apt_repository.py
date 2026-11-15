"""Real GPG/APT tests with private archives and state, never host APT sources."""
from datetime import datetime, timezone
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('apt_builder', ROOT / 'tools/build-apt-repository.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

@unittest.skipUnless(all(shutil.which(x) for x in ('gpg', 'gpgv', 'dpkg-deb', 'dpkg-scanpackages', 'apt-get', 'apt-cache')), 'Debian archive tools are required')
class AptRepositoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = tempfile.TemporaryDirectory(prefix='abstract-apt-tests-')
        cls.base = Path(cls.private.name)
        cls.home = cls.base / 'gnupg'; cls.home.mkdir(mode=0o700)
        subprocess.run(['gpg', '--homedir', str(cls.home), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '', '--quick-generate-key', 'Mellipi Test <test@example.invalid>', 'ed25519', 'sign', '0'], check=True, capture_output=True)
        result = subprocess.check_output(['gpg', '--homedir', str(cls.home), '--batch', '--with-colons', '--list-keys'], text=True)
        cls.key = next(line.split(':')[9] for line in result.splitlines() if line.startswith('fpr:'))
    @classmethod
    def tearDownClass(cls):
        subprocess.run(['gpgconf', '--homedir', str(cls.home), '--kill', 'gpg-agent'], capture_output=True)
        cls.private.cleanup()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name); self.output = self.work / 'archive'
    def package(self, version='0.1.6', payload='fixture', arch='amd64', name='abstract-fixture', depends=''):
        path = self.work / ('stage-' + name + '-' + version + '-' + arch); (path / 'DEBIAN').mkdir(parents=True, exist_ok=True)
        fields = f'Package: {name}\nVersion: {version}\nArchitecture: {arch}\nMaintainer: Test <test@example.invalid>\nDescription: Mellipi APT fixture\n'
        (path / 'DEBIAN/control').write_text(fields + (f'Depends: {depends}\n' if depends else ''))
        (path / 'fixture').write_text(payload)
        package = self.work / f'{name}_{version}_{arch}.deb'
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(path), str(package)], check=True, capture_output=True)
        return package
    def build(self, packages, **kwargs):
        return builder.build(self.output, packages, self.home, self.key, **kwargs)
    def test_desktop_release_pairs_are_checked_before_replacing_signed_archive(self):
        initial_shell = self.package(name='mellipi-shell')
        initial_desktop = self.package(name='mellipi-desktop',arch='all',depends='mellipi-shell (= 0.1.6)')
        self.build([initial_shell, initial_desktop])
        index = self.output / 'dists/noble/InRelease'
        previous = index.read_bytes()
        update_shell = self.package('0.1.7',name='mellipi-shell')
        with self.assertRaisesRegex(ValueError, 'matching shell and desktop'):
            self.build([update_shell])
        self.assertEqual(index.read_bytes(),previous)
        invalid = self.package('0.1.7',name='mellipi-desktop',arch='all',depends='mellipi-shell (>= 0.1.7)')
        with self.assertRaisesRegex(ValueError, 'exact shell version'):
            self.build([update_shell,invalid])
        valid = self.package('0.1.7',name='mellipi-desktop',arch='all',depends='mellipi-shell (= 0.1.7), dbus')
        self.build([update_shell,valid])
        report = subprocess.check_output(['python3',str(ROOT/'tools/qa-update-repository.py'),'--url',self.output.as_uri(),'--fingerprint',self.key],text=True)
        self.assertEqual({entry['candidate'] for entry in json.loads(report)['packages'].values()},{'0.1.7'})
        self.assertEqual(len(list((self.output/'pool').rglob('*.deb'))),4)
        def installed(package):
            return subprocess.check_output(['dpkg-deb','-f',str(package)],text=True)+'Status: install ok installed\n\n'
        baseline = self.work/'baseline.status'
        prior = installed(initial_shell)+installed(initial_desktop)
        command = ['python3',str(ROOT/'tools/qa-update-repository.py'),'--url',self.output.as_uri(),'--fingerprint',self.key,'--installed-status',str(baseline)]
        baseline.write_text(prior)
        missing_dependency = subprocess.run(command,capture_output=True,text=True)
        self.assertNotEqual(missing_dependency.returncode,0)
        self.assertEqual(baseline.read_text(),prior)
        original = prior+installed(self.package(name='dbus'))
        baseline.write_text(original)
        transaction = json.loads(subprocess.check_output(command,text=True))['transaction']
        self.assertEqual(transaction['upgrade'],{'version':'0.1.7','removed_packages':0})
        self.assertEqual(transaction['downgrade']['version'],'0.1.6')
        self.assertEqual(transaction['downgrade']['removed_packages'],0)
        self.assertEqual(set(transaction['downgrade']['packages']),{'mellipi-shell','mellipi-desktop'})
        self.assertEqual(baseline.read_text(),original)
    def apt_options(self, key=None):
        state = self.work / 'apt'; state.mkdir(exist_ok=True)
        for folder in ('lists/partial', 'cache/archives/partial', 'log'):
            (state / folder).mkdir(parents=True, exist_ok=True)
        (state / 'status').touch()
        source = state / 'sources.list'
        source.write_text(f'deb [signed-by={key or self.output / "abstract-archive-keyring.gpg"}] file:{self.output} noble main\n')
        return sum((['-o', value] for value in [f'Dir::Etc::sourcelist={source}', 'Dir::Etc::sourceparts=-', f'Dir::State::status={state / "status"}', f'Dir::State::lists={state / "lists"}', f'Dir::Cache={state / "cache"}', f'Dir::Log={state / "log"}', 'Debug::NoLocking=true', 'Acquire::Languages=none', 'Acquire::Retries=0', f'APT::Sandbox::User={os.getuid()}']), [])
    def test_real_apt_verifies_signature_finds_package_and_rejects_tampered_download(self):
        self.build([self.package()])
        options = self.apt_options()
        update = subprocess.run(['apt-get', *options, 'update'], capture_output=True, text=True)
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        policy = subprocess.check_output(['apt-cache', *options, 'policy', 'abstract-fixture'], text=True)
        self.assertIn('Candidate: 0.1.6', policy)
        download_dir = self.work / 'downloads'; download_dir.mkdir()
        good = subprocess.run(['apt-get', *options, 'download', 'abstract-fixture'], cwd=download_dir, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        next(download_dir.glob('*.deb')).unlink()
        deb = next((self.output / 'pool').rglob('*.deb')); deb.write_bytes(deb.read_bytes() + b'tampered')
        bad = subprocess.run(['apt-get', *options, 'download', 'abstract-fixture'], cwd=download_dir, capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('Hash Sum mismatch', bad.stdout + bad.stderr)
    def test_modified_signed_metadata_is_rejected_by_apt(self):
        self.build([self.package()])
        path = self.output / 'dists/noble/InRelease'
        path.write_bytes(path.read_bytes().replace(b'Origin: Mellipi', b'Origin: Tampered'))
        result = subprocess.run(['apt-get', *self.apt_options(), 'update'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('BADSIG', result.stdout + result.stderr)
    def test_expired_metadata_is_rejected_by_apt(self):
        self.build([self.package()], valid_days=1, now=datetime(2020, 1, 1, tzinfo=timezone.utc))
        result = subprocess.run(['apt-get', *self.apt_options(), 'update'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expired', (result.stdout + result.stderr).lower())
    def test_retains_versions_and_immutable_payloads_and_deterministic_indices(self):
        first = self.package('0.1.5'); second = self.package('0.1.6', arch='all')
        self.build([first]); old_hashes = {p.name for p in self.output.glob('dists/noble/main/binary-amd64/by-hash/SHA256/*')}
        self.build([second]); index = (self.output / 'dists/noble/main/binary-amd64/Packages').read_bytes()
        compressed = (self.output / 'dists/noble/main/binary-amd64/Packages.gz').read_bytes()
        self.assertEqual(gzip.decompress(compressed), index)
        self.assertIn(b'Version: 0.1.5', index); self.assertIn(b'Architecture: all', index)
        self.assertTrue(old_hashes.issubset({p.name for p in self.output.glob('dists/noble/main/binary-amd64/by-hash/SHA256/*')}))
        self.build([second]); self.assertEqual(compressed, (self.output / 'dists/noble/main/binary-amd64/Packages.gz').read_bytes())
        altered = self.package('0.1.5', 'altered')
        with self.assertRaisesRegex(ValueError, 'immutable'): self.build([altered])
        self.assertEqual(compressed, (self.output / 'dists/noble/main/binary-amd64/Packages.gz').read_bytes())
        self.assertFalse(any('private' in str(p.relative_to(self.output)) for p in self.output.rglob('*')))
    def test_detached_signature_and_public_key_only(self):
        self.build([self.package()])
        subprocess.run(['gpgv', '--keyring', str(self.output / 'abstract-archive-keyring.gpg'), str(self.output / 'dists/noble/Release.gpg'), str(self.output / 'dists/noble/Release')], check=True, capture_output=True)
        key = subprocess.check_output(['gpg', '--homedir', str(self.home), '--batch', '--list-packets', str(self.output / 'abstract-archive-keyring.gpg')], text=True)
        self.assertIn(':public key packet:', key); self.assertNotIn('secret', key)
        self.assertEqual(json.loads((self.output / 'archive-key.json').read_text())['fingerprint'], self.key)
    def test_rejects_unsupported_architecture_short_key_and_published_secret_home(self):
        with self.assertRaisesRegex(ValueError, 'amd64'): self.build([self.package(arch='arm64')])
        with self.assertRaisesRegex(ValueError, 'complete'): builder.build(self.output, [self.package()], self.home, self.key[-16:])
        with self.assertRaisesRegex(ValueError, 'outside'): builder.build(self.base, [self.package()], self.home, self.key)
        self.output.mkdir(); (self.output / 'pool').symlink_to(self.home, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symbolic'): self.build([self.package()])

if __name__ == '__main__': unittest.main()

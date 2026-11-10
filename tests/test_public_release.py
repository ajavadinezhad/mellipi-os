"""Site-only releases preserve authenticated archives; all state is temporary."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
prepare = load('public_release', 'prepare-public-release.py')
apt = load('public_release_apt', 'build-apt-repository.py')

@unittest.skipUnless(all(shutil.which(name) for name in ('gpg', 'gpgv', 'gpgconf', 'dpkg-deb', 'dpkg-scanpackages')), 'Debian/GPG archive tools required')
class SiteOnlyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='abstract-site-tests-')
        cls.base = Path(cls.temp.name); cls.home = cls.base / 'signer'; cls.home.mkdir(mode=0o700)
        subprocess.run(['gpg', '--homedir', str(cls.home), '--batch', '--passphrase', '', '--quick-generate-key', 'Abstract Site Test <site@example.invalid>', 'ed25519', 'sign', '0'], check=True, capture_output=True)
        info = subprocess.check_output(['gpg', '--homedir', str(cls.home), '--with-colons', '--list-keys'], text=True)
        cls.key = next(line.split(':')[9] for line in info.splitlines() if line.startswith('fpr:'))
        stage = cls.base / 'package'; (stage / 'DEBIAN').mkdir(parents=True)
        (stage / 'DEBIAN/control').write_text('Package: abstract-fixture\nVersion: 0.1.6\nArchitecture: amd64\nMaintainer: Test <site@example.invalid>\nDescription: Site-only archive fixture\n')
        (stage / 'fixture').write_text('immutable package bytes')
        cls.package = cls.base / 'abstract-fixture_0.1.6_amd64.deb'
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(stage), str(cls.package)], check=True, capture_output=True)
    @classmethod
    def tearDownClass(cls):
        subprocess.run(['gpgconf', '--homedir', str(cls.home), '--kill', 'gpg-agent'], capture_output=True)
        cls.temp.cleanup()
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.base); self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name); self.output = self.root / 'public'; self.output.mkdir()
        self.website = self.root / 'website'; self.website.mkdir()
        for name in prepare.WEBSITE_FILES:
            (self.website / name).write_text('new website ' + name)
        (self.website / 'index.html').write_text('<h1>Updated site</h1><script src="site.js"></script>')
        config = {'release': '0.1.6', 'signingFingerprint': self.key}
        (self.website / 'site-config.json').write_text(json.dumps(config))
        (self.website / 'assets').mkdir(); (self.website / 'assets/new.webp').write_bytes(b'new reviewed image')
        (self.output / 'index.html').write_text('previous public site')
        (self.output / 'assets').mkdir(); (self.output / 'assets/obsolete.webp').write_bytes(b'old image')
        (self.output / 'sources').mkdir(); (self.output / 'sources/exact-release-source.tar.gz').write_bytes(b'published source fixture')
    def archive(self, expired=False):
        kwargs = {'now': datetime(2020, 1, 1, tzinfo=timezone.utc), 'valid_days': 1} if expired else {}
        apt.build(self.output / 'apt', [self.package], self.home, self.key, **kwargs)
        self.manifest()
    def manifest(self):
        files = prepare.records(self.output)
        (self.output / prepare.MANIFEST).write_text(json.dumps({'release': '0.1.6', 'signing_fingerprint': self.key, 'sources': [name for name in files if name.startswith('sources/')], 'files': files}))
    def refresh(self):
        with patch.object(prepare, 'ROOT', self.root), patch.object(prepare, 'export_themes') as export, redirect_stdout(io.StringIO()):
            result = prepare.assemble(self.output, site_only=True)
            export.assert_called_once()
            return result
    def test_site_refresh_does_not_rewrite_any_signed_archive_or_source_file(self):
        self.archive()
        immutable = {str(p.relative_to(self.output)): (p.read_bytes(), p.stat().st_mtime_ns) for directory in ('apt', 'sources') for p in (self.output / directory).rglob('*') if p.is_file()}
        # A site-only refresh succeeds without even access to the signing home.
        with patch.object(prepare.subprocess, 'run', wraps=subprocess.run) as commands:
            manifest = self.refresh()
        self.assertFalse(any('build-apt-repository.py' in str(call.args[0]) or '--gnupg-home' in call.args[0] for call in commands.call_args_list))
        for name, (payload, modified) in immutable.items():
            self.assertEqual((self.output / name).read_bytes(), payload, name)
            self.assertEqual((self.output / name).stat().st_mtime_ns, modified, name)
        self.assertIn('Updated site', (self.output / 'index.html').read_text())
        self.assertRegex((self.output / 'index.html').read_text(), r'site\.js\?v=[a-f0-9]{12}')
        self.assertFalse((self.output / 'assets/obsolete.webp').exists())
        self.assertTrue((self.output / 'assets/new.webp').is_file())
        self.assertEqual(manifest['files'], prepare.records(self.output))
    def test_tampered_package_is_rejected_before_site_files_change_even_if_plain_manifest_matches(self):
        self.archive(); package = next((self.output / 'apt/pool').rglob('*.deb')); package.write_bytes(package.read_bytes() + b'changed')
        self.manifest()
        with patch.object(prepare, 'ROOT', self.root), patch.object(prepare, 'export_themes') as export:
            with self.assertRaisesRegex(ValueError, 'payload mismatch'): prepare.assemble(self.output, site_only=True)
            export.assert_not_called()
        self.assertEqual((self.output / 'index.html').read_text(), 'previous public site')
    def test_expired_archive_and_manifest_mismatch_fail_without_mutating_the_site(self):
        self.archive(expired=True)
        with self.assertRaisesRegex(ValueError, 'expired'): self.refresh()
        self.assertEqual((self.output / 'index.html').read_text(), 'previous public site')
        self.archive()
        (self.output / 'sources/exact-release-source.tar.gz').write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'manifest'): self.refresh()
        self.assertEqual((self.output / 'index.html').read_text(), 'previous public site')
    def test_cli_refuses_signing_package_or_source_flags_in_site_only_mode(self):
        for flags in (['--packages', 'fixture.deb'], ['--signing-key', self.key], ['--gnupg-home', str(self.home)], ['--sources']):
            with self.subTest(flags=flags), patch('sys.argv', ['prepare-public-release.py', '--site-only', *flags]), patch.object(prepare, 'assemble') as stage, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error: prepare.main()
                self.assertEqual(error.exception.code, 2); stage.assert_not_called()

if __name__ == '__main__': unittest.main()

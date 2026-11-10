"""Compatibility at the rename boundary; never change the host's APT state."""
import importlib.util,os,tempfile,unittest
from pathlib import Path
from tests.test_desktop_package import builder
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rename_source',ROOT/'tools/migrate-update-source.py');migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)

class MellipiRenameTests(unittest.TestCase):
    def setup_root(self,path):
        old=path/'etc/apt/sources.list.d/abstract.sources';old.parent.mkdir(parents=True)
        old.write_text('Types: deb\nURIs: '+migration.OLD_URI+'\nSuites: noble\nComponents: main\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/abstract-archive-keyring.gpg\n');old.chmod(0o644)
        for name in ('etc/apt/keyrings/abstract-archive-keyring.gpg',migration.KEY.lstrip('/')):
            key=path/name;key.parent.mkdir(parents=True,exist_ok=True);key.write_bytes(b'public-test-key');key.chmod(0o644)
        return old
    def test_known_source_migrates_atomically_keeps_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.setup_root(root);original=old.read_bytes()
            self.assertEqual(migration.migrate(root,lambda _:migration.FINGERPRINT,os.getuid()),'migrated')
            self.assertFalse(old.exists());self.assertEqual(old.with_name('mellipi.sources').read_text(),migration.EXPECTED)
            self.assertEqual((root/'var/lib/abstract/migrations/abstract.sources.pre-mellipi').read_bytes(),original)
            self.assertEqual(migration.migrate(root,lambda _:migration.FINGERPRINT,os.getuid()),'not-needed')
    def test_custom_source_wrong_key_or_existing_different_destination_is_preserved(self):
        for case in ('custom','key','destination','duplicate'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);old=self.setup_root(root)
                if case=='custom':old.write_text(old.read_text().replace(migration.OLD_URI,'https://example.invalid/apt'))
                if case=='duplicate':old.write_text(old.read_text()+'Suites: noble\n')
                if case=='destination':old.with_name('mellipi.sources').write_text('custom configuration\n')
                original=old.read_bytes();reader=lambda _:('0'*40 if case=='key' else migration.FINGERPRINT)
                self.assertEqual(migration.migrate(root,reader,os.getuid()),'kept-custom-source');self.assertEqual(old.read_bytes(),original)
    def test_symlink_source_is_never_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.setup_root(root);target=old.with_name('private');old.rename(target);old.symlink_to(target.name)
            self.assertEqual(migration.migrate(root,lambda _:migration.FINGERPRINT,os.getuid()),'kept-custom-source');self.assertTrue(old.is_symlink())
    def test_transitional_packages_allow_future_mellipi_upgrades_and_have_no_scripts(self):
        for kind in ('shell','desktop'):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);builder.stage_transition(root,'0.1.8',kind);text=(root/'DEBIAN/control').read_text()
                self.assertIn('Package: abstract-'+kind,text);self.assertIn('Depends: mellipi-'+kind+' (>= 0.1.8)',text)
                self.assertEqual(sorted(p.name for p in (root/'DEBIAN').iterdir()),['control'])
    def test_user_facing_qml_and_wallpaper_branding_is_mellipi(self):
        import re
        for path in (ROOT/'native').iterdir():
            if path.suffix not in ('.qml','.svg'):continue
            self.assertIsNone(re.search(r'\b(?:Abstract|ABSTRACT)\b',path.read_text()),str(path))
        self.assertIn('Mellipi',(ROOT/'native/lock-textbox-render.h').read_text())

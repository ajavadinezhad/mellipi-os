import io
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import file_archives as archives


def publish(source, target):
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    source.rename(target)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def assert_no_staging(self):
        self.assertFalse(list(self.root.glob('.mellipi-*')))

    def test_preview_lists_contents_without_extracting(self):
        target = self.root / 'sample.zip'
        with zipfile.ZipFile(target, 'w') as arc:
            arc.writestr('notes/', b'')
            arc.writestr('notes/hello.txt', b'hello')
        self.assertEqual(archives.preview_archive(target),
                         ([('notes', True, 0), ('notes/hello.txt', False, 5)], False))
        self.assertEqual(list(self.root.iterdir()), [target])
        with patch.object(archives, 'PREVIEW_ROWS', 1):
            self.assertEqual(archives.preview_archive(target), ([('notes', True, 0)], True))

    def test_preview_tar_supported_compression_and_scan_limit(self):
        for suffix, mode in (('tar', 'w'), ('tgz', 'w:gz'), ('tar.bz2', 'w:bz2'), ('tar.xz', 'w:xz')):
            with self.subTest(mode=mode):
                target = self.root / f'sample.{suffix}'
                with tarfile.open(target, mode) as arc:
                    item = tarfile.TarInfo('./one.txt')
                    item.size = 20000
                    arc.addfile(item, io.BytesIO(b'z' * item.size))
                    arc.addfile(tarfile.TarInfo('two.txt'))
                expected = ('one.txt', False, item.size)
                self.assertEqual(archives.preview_archive(target),
                                 ([expected, ('two.txt', False, 0)], False))
                with patch.object(archives, 'PREVIEW_BYTES', 12000):
                    self.assertEqual(archives.preview_archive(target), ([expected], True))
        self.assert_no_staging()

    def test_preview_rejects_unsafe_paths_and_symlinks(self):
        target = self.root / 'bad.zip'
        with zipfile.ZipFile(target, 'w') as arc:
            arc.writestr('../outside', 'bad')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            archives.preview_archive(target)
        link = self.root / 'link.zip'
        link.symlink_to(target)
        with self.assertRaises(OSError):
            archives.preview_archive(link)

    def test_compress_zip_from_nested_folder_and_empty_directory(self):
        source = self.root / 'My folder'
        (source / 'empty').mkdir(parents=True)
        (source / 'greeting.txt').write_text('Hello!')
        target = archives.compress([source], self.root / 'copy.zip', publish)
        output = archives.extract_here(target, publish)
        self.assertEqual((output / source.name / 'greeting.txt').read_text(), 'Hello!')
        self.assertTrue((output / source.name / 'empty').is_dir())
        self.assert_no_staging()

    def test_tar_modes_support_root_entry_unicode_and_long_paths(self):
        for suffix, mode in (('tar', 'w'), ('tgz', 'w:gz'), ('tar.bz2', 'w:bz2'), ('tar.xz', 'w:xz')):
            with self.subTest(mode=mode):
                target = self.root / f'example-{suffix}.{suffix}'
                directory = 'é' * 55
                with tarfile.open(target, mode, format=tarfile.PAX_FORMAT) as arc:
                    root = tarfile.TarInfo('.')
                    root.type = tarfile.DIRTYPE
                    arc.addfile(root)
                    item = tarfile.TarInfo('./' + directory + '/file')
                    item.size = 3
                    arc.addfile(item, io.BytesIO(b'abc'))
                output = archives.extract_here(target, publish)
                self.assertEqual((output / directory / 'file').read_bytes(), b'abc')
        self.assert_no_staging()

    def test_zip_escape_variants_and_symlinks_cannot_publish(self):
        names = ['../../outside', '/root/owned', r'C:\outside', 'x/../outside']
        for name in names:
            with self.subTest(name=name):
                target = self.root / 'bad.zip'
                with zipfile.ZipFile(target, 'w') as arc:
                    arc.writestr('safe.txt', 'good')
                    arc.writestr(name, 'bad')
                with self.assertRaises(ValueError):
                    archives.extract_here(target, publish)
                self.assertFalse((self.root / 'bad').exists())
        with zipfile.ZipFile(target, 'w') as arc:
            item = zipfile.ZipInfo('link')
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            arc.writestr(item, '/etc/passwd')
        with self.assertRaises(ValueError):
            archives.extract_here(target, publish)
        self.assert_no_staging()

    def test_tar_links_and_huge_metadata_are_rejected(self):
        target = self.root / 'bad.tar'
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.XHDTYPE):
            with self.subTest(kind=kind):
                item = tarfile.TarInfo('link')
                item.type = kind
                if kind == tarfile.XHDTYPE:
                    item.size = archives.CHUNK + 1
                else:
                    item.linkname = 'outside'
                target.write_bytes(item.tobuf() + b'\0' * 1024)
                with self.assertRaises(ValueError):
                    archives.extract_here(target, publish)
        self.assert_no_staging()

    def test_truncated_tar_not_published(self):
        target = self.root / 'truncated.tgz'
        with tarfile.open(target, 'w:gz') as arc:
            item = tarfile.TarInfo('file')
            item.size = 3
            arc.addfile(item, io.BytesIO(b'abc'))
        target.write_bytes(target.read_bytes()[:-4])
        with self.assertRaises((EOFError, ValueError)):
            archives.extract_here(target, publish)
        self.assertFalse((self.root / 'truncated').exists())
        self.assert_no_staging()

    def test_limits_and_existing_outputs_do_not_clobber(self):
        target = self.root / 'existing.zip'
        with zipfile.ZipFile(target, 'w') as arc:
            arc.writestr('one', 'hello')
        with patch.object(archives, 'MAX_BYTES', 4):
            with self.assertRaises(ValueError):
                archives.extract_here(target, publish)
        (self.root / 'existing').mkdir()
        important = self.root / 'existing' / 'one'
        important.write_text('keep')
        with self.assertRaises(ValueError):
            archives.extract_here(target, publish)
        with self.assertRaises(ValueError):
            archives.compress([important], target, publish)
        self.assertEqual(important.read_text(), 'keep')
        self.assert_no_staging()

    def test_compress_symlink_and_nested_output_are_refused(self):
        source = self.root / 'dir'
        source.mkdir()
        (source / 'link').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'outside'):
            archives.compress([source], source / 'new.zip', publish)
        destination = self.root / 'dir.zip'
        with self.assertRaisesRegex(ValueError, 'Links'):
            archives.compress([source], destination, publish)
        self.assertFalse(destination.exists())
        self.assert_no_staging()

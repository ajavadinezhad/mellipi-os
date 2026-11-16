"""Exercise Files transfer decisions without changing the running session."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from file_transfers import Cancelled, CancelToken, Transfer, unique_name
from mellipi_files import Files, rename_no_replace


class FilesTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_keep_both_preserves_utf8_and_extension_at_name_limit(self):
        with TemporaryDirectory() as directory:
            original = Path(directory) / (('é' * 125) + '.txt')
            original.write_bytes(b'first')
            first = unique_name(original)
            first.write_bytes(b'copy')
            second = unique_name(original)
            self.assertTrue(first.name.endswith(' (copy).txt'))
            self.assertTrue(second.name.endswith(' (copy 2).txt'))
            self.assertLessEqual(len(second.name.encode('utf-8')), 255)
            self.assertEqual(original.read_bytes(), b'first')

    def wait_for(self, condition):
        for _ in range(150):
            if condition():
                return
            QTest.qWait(10)
        self.fail('Timed out waiting for transfer')

    def test_collision_choices_preserve_destination(self):
        for choice in ('keep', 'skip', 'cancel'):
            with self.subTest(choice=choice), TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / 'report.txt'
                source.write_text('incoming')
                target = root / 'target'
                target.mkdir()
                existing = target / source.name
                existing.write_text('existing')
                window = Files(target)
                window.show()
                window.activateWindow()
                window.view.setFocus()
                self.application.processEvents()
                try:
                    window.transfer_paths([source], target)
                    strip = window.transfer_strip
                    self.wait_for(strip.keep.isVisible)
                    self.assertTrue(strip.skip.isVisible())
                    self.assertTrue(strip.cancel.isVisible())
                    self.assertIs(self.application.focusWidget(), strip.skip)
                    self.assertEqual(existing.read_text(), 'existing')
                    getattr(strip, choice).click()
                    self.wait_for(lambda: window.job is None)
                    self.assertFalse(strip.isVisible())
                    self.assertIs(self.application.focusWidget(), window.view)
                    self.assertEqual(existing.read_text(), 'existing')
                    self.assertEqual(source.read_text(), 'incoming')
                    copy = target / 'report (copy).txt'
                    self.assertEqual(copy.exists(), choice == 'keep')
                    if choice == 'keep':
                        self.assertEqual(copy.read_text(), 'incoming')
                    elif choice == 'cancel':
                        self.assertIn('Transfer canceled', window.statusBar().currentMessage())
                finally:
                    if window.job:
                        window.transfer_strip.resolve('cancel')
                        self.wait_for(lambda: window.job is None)
                    window.close()

    def test_cancel_during_cross_device_copy_does_not_trash_or_publish(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            target.mkdir()
            source = root / 'large.bin'
            source.write_bytes(b'x' * (2 * 1024 * 1024))
            token, trashed = CancelToken(), []

            def rename(old, new):
                if old == source:
                    import errno
                    raise OSError(errno.EXDEV, 'Cross-device move')
                return rename_no_replace(old, new)

            def progress(data):
                if data.get('currentTotal'):
                    token.cancel()

            transfer = Transfer(target, rename, trashed.append, token, progress)
            with self.assertRaises(Cancelled):
                transfer.run([source], move=True)
            self.assertTrue(source.exists())
            self.assertEqual(trashed, [])
            self.assertEqual(list(target.iterdir()), [])

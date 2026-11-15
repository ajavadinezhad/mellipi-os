"""Clipboard MIME routing with no real clipboard or filesystem transfers."""
from pathlib import Path
import unittest

from PyQt5.QtCore import QMimeData, QUrl

from mellipi_files import MAX_CLIPBOARD_BYTES, MAX_SOURCES, clipboard_transfer, local_paths


class FileClipboardTests(unittest.TestCase):
    def test_cut_rejects_different_file_lists(self):
        mime = QMimeData()
        mime.setUrls([QUrl('file:///tmp/other.txt')])
        mime.setData('x-special/gnome-copied-files', b'cut\nfile:///tmp/intended.txt\n')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            clipboard_transfer(mime)

    def test_matching_cut_and_gnome_only_work(self):
        mime = QMimeData()
        mime.setUrls([QUrl('file://localhost/tmp/cut%20me')])
        mime.setData('x-special/gnome-copied-files', b'cut\nfile:///tmp/cut%20me')
        self.assertEqual(clipboard_transfer(mime), ([Path('/tmp/cut me')], True))
        mime.removeFormat('text/uri-list')
        self.assertEqual(clipboard_transfer(mime), ([Path('/tmp/cut me')], True))

    def test_remote_authority_rejected_for_clipboard_and_drop(self):
        remote = QUrl('file://example.invalid/tmp/file')
        self.assertEqual(local_paths([remote]), [])
        mime = QMimeData()
        mime.setUrls([remote])
        with self.assertRaisesRegex(ValueError, 'local files'):
            clipboard_transfer(mime)

    def test_bounds_and_plain_uri_copy(self):
        mime = QMimeData()
        mime.setData('text/uri-list', b'# comment\r\nfile:///tmp/copy%20me\r\n')
        self.assertEqual(clipboard_transfer(mime), ([Path('/tmp/copy me')], False))
        mime.setData('text/uri-list', b'x' * (MAX_CLIPBOARD_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'too large'):
            clipboard_transfer(mime)
        mime.setData('text/uri-list', b'file:///tmp/a\n' * (MAX_SOURCES + 1))
        with self.assertRaisesRegex(ValueError, 'at most'):
            clipboard_transfer(mime)

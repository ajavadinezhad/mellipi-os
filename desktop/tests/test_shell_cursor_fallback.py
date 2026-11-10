"""Optional cursor artwork cannot break pointer events on a clean installation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from qt_compat import QApplication, QEvent, Qt, QT5
if QT5:
    from PyQt5.QtGui import QWindow
else:
    from PySide6.QtGui import QWindow
import shell_cursor

class CursorFallbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='abstract-cursor-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.icons = Path(self.temp.name)
        self.file = self.icons / 'fixture' / 'cursors/left_ptr'
        self.file.parent.mkdir(parents=True)
        self.path_patch = patch.object(shell_cursor, 'Path', return_value=self.icons)
        self.theme_patch = patch('application_theme.cursor_name', return_value='fixture')
        self.path_patch.start(); self.theme_patch.start()
        self.addCleanup(self.path_patch.stop); self.addCleanup(self.theme_patch.stop)
        shell_cursor._CACHE.clear()
        self.addCleanup(shell_cursor._CACHE.clear)
    def test_missing_file_is_cached_and_pointer_timer_remains_usable(self):
        controller = shell_cursor.CursorController(self.app)
        window = QWindow()
        try:
            with patch.object(shell_cursor, 'read_arrow', wraps=shell_cursor.read_arrow) as reads:
                for _ in range(4):
                    controller.eventFilter(window, QEvent(QEvent.Enter))
                    self.app.processEvents()
                    self.assertTrue(controller.owned)
                    self.assertEqual(self.app.overrideCursor().shape(), Qt.ArrowCursor)
                self.assertEqual(reads.call_count, 1)
            controller.eventFilter(window, QEvent(QEvent.Leave))
            self.assertFalse(controller.owned)
            self.assertIsNone(self.app.overrideCursor())
        finally:
            controller.release(); window.close(); controller.deleteLater(); self.app.processEvents()
    def test_corrupt_and_truncated_artwork_falls_back_without_raising(self):
        for payload in (b'not an Xcursor', b'Xcur', b'Xcur' + struct.pack('<III', 16, 65536, 0)):
            with self.subTest(payload=payload):
                self.file.write_bytes(payload); shell_cursor._CACHE.clear()
                self.assertEqual(shell_cursor.arrow('dark', '#78b7ff').shape(), Qt.ArrowCursor)
    def test_fallback_cache_stays_bounded_across_color_changes(self):
        for index in range(40):
            self.assertEqual(shell_cursor.arrow('dark', f'#{index:06x}').shape(), Qt.ArrowCursor)
            self.assertLessEqual(len(shell_cursor._CACHE), 12)
    def test_valid_artwork_keeps_accent_variants(self):
        image_type = 0xfffd0002
        self.file.write_bytes(b'Xcur' + struct.pack('<III', 16, 65536, 1) + struct.pack('<III', image_type, 24, 28) + struct.pack('<9I', 36, image_type, 24, 1, 2, 2, 0, 0, 0) + struct.pack('<4I', 0xffffffff, 0xff000000, 0xffffffff, 0xff000000))
        blue = shell_cursor.arrow('dark', '#78b7ff')
        green = shell_cursor.arrow('dark', '#8ab775')
        self.assertEqual(blue.shape(), Qt.BitmapCursor)
        self.assertFalse(blue.pixmap().isNull())
        self.assertNotEqual(blue.pixmap().toImage(), green.pixmap().toImage())

if __name__ == '__main__': unittest.main()

"""Exercise mouse delivery through the real Qt Files event filter."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from mellipi_files import Files


class FilesPointerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_moves_and_clicks_including_resize_margin_do_not_raise(self):
        with TemporaryDirectory() as directory:
            window = Files(Path(directory))
            window.show()
            central = window.centralWidget()
            # SIP reports Python event filter exceptions to sys.excepthook.
            with patch.object(sys, 'excepthook') as exception:
                QTest.mouseMove(central, QPoint(2, 2))
                QTest.mouseClick(central, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
                QTest.mouseMove(central, QPoint(75, 50))
                QTest.mouseClick(central, Qt.MouseButton.LeftButton, pos=QPoint(75, 50))
                QTest.mouseClick(window.places[Path.home()], Qt.MouseButton.LeftButton)
                exception.assert_not_called()
            self.assertEqual(window.folder, Path.home())
            window.close()
            self.application.processEvents()

    def test_bookmarks_are_shared_and_disambiguate_matching_folder_names(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'Work' / 'Reports', root / 'Personal' / 'Reports'
            for folder in (first, second):
                folder.mkdir(parents=True)
            first_window, second_window = Files(root), Files(root)
            try:
                for window in (first_window, second_window):
                    window.bookmark_settings = QSettings(str(root / 'files.ini'), QSettings.Format.IniFormat)
                first_window.add_bookmark(first)
                second_window.add_bookmark(second)
                first_window.add_bookmark(first)
                first_window.render_bookmarks()
                action, = [item for item in first_window.bookmark_menu.actions() if str(first.parent) in item.text()]
                self.assertIn(str(second.parent), ' '.join(item.text() for item in first_window.bookmark_menu.actions()))
                action.trigger()
                self.assertEqual(first_window.folder, first)

                second_window.change_bookmark(str(first), 'Work reports')
                self.assertEqual(first_window.read_bookmarks(), {str(first): 'Work reports', str(second): 'Reports'})
                first_window.change_bookmark(str(first))
                self.assertEqual(second_window.read_bookmarks(), {str(second): 'Reports'})
                self.assertTrue(first.is_dir())
            finally:
                first_window.close()
                second_window.close()
                self.application.processEvents()

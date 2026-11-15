"""Exercise mouse delivery through the real Qt Files event filter."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
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

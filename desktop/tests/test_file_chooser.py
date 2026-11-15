"""Exercise selection in the real Mellipi chooser without touching user files."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyQt6.QtWidgets import QApplication, QDialog
from file_chooser import FileChooser


class FileChooserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_existing_file_and_name_filter(self):
        with TemporaryDirectory() as dirname:
            file = Path(dirname) / 'drawing.svg'
            file.touch()
            dialog = FileChooser(directory=str(file), filters='Images (*.svg);;All files (*)')
            self.assertTrue(dialog.testOption(FileChooser.Option.DontUseNativeDialog))
            self.assertEqual(dialog.selectedNameFilter(), 'Images (*.svg)')
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selectedFiles(), [str(file)])
            dialog.deleteLater()

    def test_folder_and_new_save_name(self):
        with TemporaryDirectory() as dirname:
            folder = FileChooser(directory=dirname, mode=FileChooser.FileMode.Directory)
            self.assertTrue(folder.testOption(FileChooser.Option.ShowDirsOnly))
            folder.accept()
            self.assertEqual(folder.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(folder.selectedFiles(), [dirname])
            folder.deleteLater()
            path = str(Path(dirname) / 'new.txt')
            save = FileChooser(directory=path, mode=FileChooser.FileMode.AnyFile, save=True)
            save.accept()
            self.assertEqual(save.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(save.selectedFiles(), [path])
            self.assertFalse(Path(path).exists())
            save.deleteLater()

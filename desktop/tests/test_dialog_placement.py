"""Save and close prompts belong to the app window that opened them."""
import tempfile
import unittest

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from file_chooser import FileChooser
from qt_app import AppWindow, exec_owned_dialog, themed_choice


class DialogPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = AppWindow('Mellipi Editor')
        area = self.owner.screen().availableGeometry()
        self.owner.setGeometry(area.x() + 60, area.y() + 55,
                               min(630, area.width()), min(510, area.height()))
        self.owner.show()
        self.app.processEvents()

    def tearDown(self):
        self.owner.close()

    def assert_dialog(self, dialog):
        self.assertIs(dialog.parentWidget().window(), self.owner)
        self.assertEqual(dialog.windowModality(), Qt.WindowModality.WindowModal)
        available = self.owner.screen().availableGeometry()
        desired = self.owner.frameGeometry().center() - QPoint(dialog.width() // 2, dialog.height() // 2)
        expected_x = max(available.left(), min(desired.x(), available.right() + 1 - dialog.width()))
        expected_y = max(available.top(), min(desired.y(), available.bottom() + 1 - dialog.height()))
        self.assertLessEqual(abs(dialog.x() - expected_x), 2)
        self.assertLessEqual(abs(dialog.y() - expected_y), 2)

    def test_save_chooser_centers_over_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            dialog = FileChooser(self.owner, 'Save copy', folder, save=True)
            QTimer.singleShot(0, dialog.reject)
            self.assertEqual(exec_owned_dialog(dialog), QDialog.DialogCode.Rejected)
            self.assert_dialog(dialog)
            dialog.deleteLater()

    def test_close_prompt_centers_and_cancel_remains_default(self):
        observed = []
        def inspect_and_cancel():
            dialog = QApplication.activeModalWidget()
            try:
                self.assert_dialog(dialog)
                self.assertEqual(dialog.focusWidget().objectName(), 'promptCancel')
            except Exception as error:
                observed.append(error)
            finally:
                dialog.reject()
        QTimer.singleShot(0, inspect_and_cancel)
        self.assertEqual(themed_choice(self.owner, 'Unsaved changes', 'Save the document?',
                                       'Save', 'Cancel', 'Discard'), QDialog.DialogCode.Rejected)
        self.assertEqual(observed, [])

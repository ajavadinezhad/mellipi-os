"""Focused fields keep their content in place in the shared Qt style."""
import unittest

from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from qt_app import BASE_STYLE, ThemeWatch


class InputAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def test_high_contrast_focus_keeps_field_size_and_text_position(self):
        window = QWidget()
        fields = QVBoxLayout(window)
        edit = QLineEdit('42')
        spin = QSpinBox()
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem('Choice')
        for field in (edit, spin, combo):
            fields.addWidget(field)
        theme = ThemeWatch(window)
        window.setStyleSheet(BASE_STYLE % dict(theme.tokens, focus_width=2))
        window.resize(280, 160)
        window.show()
        try:
            for field in (edit, spin, combo):
                with self.subTest(field=type(field).__name__):
                    target = field if field is edit else field.findChild(QLineEdit)
                    other = spin if field is edit else edit
                    other.setFocus()
                    self.app.processEvents()
                    cursor = edit.cursorRect() if field is edit else None
                    baseline = (field.sizeHint(), field.geometry(), target.geometry())
                    field.setFocus()
                    self.app.processEvents()
                    self.assertTrue(field.hasFocus() or target.hasFocus())
                    self.assertEqual((field.sizeHint(), field.geometry(), target.geometry()), baseline)
                    if cursor is not None:
                        self.assertEqual(edit.cursorRect(), cursor)
        finally:
            window.close()

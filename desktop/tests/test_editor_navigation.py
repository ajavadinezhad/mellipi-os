"""Exercise Editor line navigation through its real Qt widgets."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from mellipi_editor import Editor


class EditorNavigationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.source = root / 'example.txt'
        self.original = b'\xef\xbb\xbf' + ('\r\n'.join(f'log {n}\u00a0' for n in range(1, 101)) + '\r\n').encode()
        self.source.write_bytes(self.original)
        self.editor = Editor([str(self.source)], recovery=root / 'drafts')
        self.addCleanup(self.editor.close)
        self.editor.resize(520, 340)
        self.editor.show()
        self.app.processEvents()
        self.doc = self.editor.document()

    def test_toolbar_compacts_at_large_text_and_restores_labels(self):
        settings = self.source.with_name('settings.json')
        settings.write_text(json.dumps({'textScale': 1.5, 'highContrast': True}))
        self.editor.theme_watch.path = settings
        self.editor.theme_watch.reload()
        self.editor.resize(520, 440)
        self.app.processEvents()
        self.assertEqual(self.editor.width(), 520)
        self.assertEqual(self.editor.save_button.text(), 'Save')
        labels = ('New', 'Open', 'Find', 'Replace')
        for button, label in zip(self.editor.compact_actions, labels):
            self.assertEqual(button.text(), '')
            self.assertEqual(button.accessibleName(), label)
            self.assertEqual(button.toolTip(), label)
            self.assertFalse(button.icon().isNull())
            self.assertGreaterEqual(button.iconSize().width(), 22)
        self.editor.show_replace()
        self.app.processEvents()
        self.assertGreater(self.editor.query.width(), 160)
        self.editor.resize(900, 440)
        self.app.processEvents()
        self.assertEqual(tuple(button.text() for button in self.editor.compact_actions), labels)

    def test_keyboard_jumps_to_last_empty_line_without_editing(self):
        QTest.keyClick(self.doc, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.editor.line_input.hasFocus())
        QTest.keyClicks(self.editor.line_input, '101')
        QTest.keyClick(self.editor.line_input, Qt.Key.Key_Return)
        self.assertTrue(self.editor.line_panel.isHidden())
        self.assertTrue(self.doc.hasFocus())
        self.assertEqual(self.editor.position.text(), 'Line 101, column 1')
        self.assertFalse(self.doc.document().isModified())
        self.assertEqual(self.doc.data(), self.original)
        self.assertTrue(self.editor.save())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.editor.recovery.glob("*.json")), [])

    def test_invalid_lines_do_not_move_and_escape_cancels(self):
        QTest.mouseClick(self.editor.position, Qt.MouseButton.LeftButton)
        original_pos = self.doc.textCursor().position()
        for value in ('0', '102', '1.5', 'x', '999999999999999'):
            self.editor.line_input.setText(value)
            QTest.keyClick(self.editor.line_input, Qt.Key.Key_Return)
            self.assertEqual(self.doc.textCursor().position(), original_pos)
            self.assertIn('1 to 101', self.editor.status.text())
            self.assertTrue(self.editor.line_input.hasFocus())
        QTest.keyClick(self.editor.line_input, Qt.Key.Key_Escape)
        self.assertTrue(self.editor.line_panel.isHidden())
        self.assertTrue(self.doc.hasFocus())

    def test_switching_tabs_closes_navigation_for_previous_document(self):
        self.editor.new_tab()
        self.editor.tabs.setCurrentWidget(self.doc)
        self.editor.show_go_to_line()
        self.editor.tabs.setCurrentIndex(1)
        self.assertTrue(self.editor.line_panel.isHidden())
        self.assertEqual(self.editor.position.text(), 'Line 1, column 1')

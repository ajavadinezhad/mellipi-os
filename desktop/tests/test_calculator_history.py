"""Exercise Calculator's session-only history with Qt and real key events."""
from unittest import TestCase

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from mellipi_calculator import Calculator, HISTORY_LIMIT


class CalculatorHistoryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Calculator()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    def calculate(self, expression):
        self.window.field.setText(expression)
        self.window.edited()
        QTest.keyClick(self.window.field, Qt.Key.Key_Return)

    def test_keyboard_history_recall_copy_and_escape(self):
        window = self.window
        self.calculate('12*3')
        self.calculate('4+5')
        self.calculate('2/0')
        self.assertEqual(window.history.count(), 2)
        QTest.keyClick(window.field, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertTrue(window.history.isVisible())
        self.assertTrue(window.history.hasFocus())
        QTest.keyClick(window.history, Qt.Key.Key_Down)
        window.history_copy.click()
        self.assertEqual(self.app.clipboard().text(), '36')
        self.assertEqual(window.field.text(), '2/0')
        QTest.keyClick(window.history, Qt.Key.Key_Return)
        self.assertEqual(window.field.text(), '12*3')
        self.assertTrue(window.field.hasFocus())
        QTest.keyClick(window.field, Qt.Key.Key_Escape)
        self.assertFalse(window.history.isVisible())
        self.assertEqual(window.field.text(), '12*3')

    def test_history_is_bounded_and_can_be_cleared(self):
        window = self.window
        for number in range(HISTORY_LIMIT + 3):
            self.calculate(f'{number}+1')
        self.calculate(f'{HISTORY_LIMIT + 2}+1')
        self.assertEqual(window.history.count(), HISTORY_LIMIT)
        self.assertEqual(window.history.item(HISTORY_LIMIT - 1).text(), '3+1 = 4')
        other_window = Calculator()
        self.addCleanup(other_window.deleteLater)
        self.assertEqual(other_window.history.count(), 0)
        window.history_button.click()
        window.history_clear.click()
        self.assertEqual(window.history.count(), 0)
        self.assertFalse(window.history_copy.isEnabled())
        self.assertEqual(window.last_expression, '')

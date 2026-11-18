"""Exercise Calculator's session-only history with Qt and real key events."""
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton

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

    def test_percentage_shortcuts_calculate_and_reject_zero_base(self):
        def run(change, first, second):
            def enter(dialog):
                fields = dialog.findChildren(QLineEdit)
                fields[0].setText(first)
                fields[1].setText(second)
                next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Calculate').click()
                return dialog.result()
            with patch('mellipi_calculator.exec_owned_dialog', side_effect=enter):
                self.window.percentage(change)
        run(False, '15', '240')
        self.assertEqual(self.window.field.text(), '36')
        run(True, '80', '100')
        self.assertEqual(self.window.field.text(), '25')
        self.assertIn('(%)', self.window.feedback.text())
        run(True, '0', '100')
        self.assertEqual(self.window.field.text(), '25')
        self.assertEqual(self.window.history.count(), 2)

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

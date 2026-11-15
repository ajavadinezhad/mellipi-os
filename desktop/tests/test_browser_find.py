"""Exercise browser page search without a network or an installed session."""
from enum import IntFlag
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from mellipi_browser import Browser

class Page:
    class FindFlag(IntFlag):
        FindBackward = 1


class BrowserFindTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.sip import delete
        settings = SimpleNamespace(WebAttribute=Mock(), setAttribute=Mock())
        profile = Mock()
        profile.settings.return_value = settings
        self.browser = Browser((lambda *_: profile, Page, None, None), private=True)
        self.addCleanup(delete, self.browser)
        self.browser.show()
        self.app.processEvents()

    def attach_page(self, tab):
        # Only rendering/search is mocked; focus, keyboard navigation and tab
        # selection are exercised through the real Browser widgets.
        tab.view = QWidget(tab)
        tab.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        tab.view.findText = Mock()
        tab.view.url = Mock(return_value=QUrl())
        tab.view.history = Mock()
        tab.view.page = Mock()
        tab.layout_.addWidget(tab.view)
        return tab.view

    def test_keyboard_find_navigation_and_escape(self):
        current = self.attach_page(self.browser.tabs.currentWidget())
        QTest.keyClick(self.browser.address, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.browser.find_input.hasFocus())
        QTest.keyClicks(self.browser.find_input, 'mint')
        self.assertEqual(current.findText.call_args.args[0], 'mint')
        QTest.keyClick(self.browser.find_input, Qt.Key.Key_Return)
        self.assertEqual(current.findText.call_args.args[1], Page.FindFlag(0))
        QTest.mouseClick(self.browser.find_previous, Qt.MouseButton.LeftButton)
        self.assertEqual(current.findText.call_args.args[1], Page.FindFlag.FindBackward)
        callback = current.findText.call_args.args[2]
        callback(False)
        self.assertEqual(self.browser.find_result.text(), 'No match')
        QTest.keyClick(self.browser.find_input, Qt.Key.Key_Escape)
        self.assertTrue(self.browser.find_bar.isHidden())
        current.findText.assert_called_with('')
        callback(False)
        self.assertEqual(self.browser.find_result.text(), '')

    def test_switching_tabs_drops_stale_results_and_retargets_search(self):
        first = self.attach_page(self.browser.tabs.currentWidget())
        other = self.browser.add_tab(foreground=False)
        second = self.attach_page(other)
        self.browser.show_find()
        self.browser.find_input.setText('mint')
        stale = first.findText.call_args.args[2]
        self.browser.tabs.setCurrentWidget(other)
        first.findText.assert_called_with('')
        self.assertEqual(second.findText.call_args.args[0], 'mint')
        stale(False)
        self.assertEqual(self.browser.find_result.text(), '')

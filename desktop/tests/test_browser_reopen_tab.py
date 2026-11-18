"""Exercise closed-tab recovery using the actual Browser widgets, without networking."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTabBar, QWidget

from mellipi_browser import Browser, VisitHistory


class ReopenTabTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_browser(self):
        from PyQt6.sip import delete

        settings = SimpleNamespace(WebAttribute=Mock(), setAttribute=Mock())
        profile = Mock()
        profile.settings.return_value = settings
        browser = Browser((lambda *_: profile, None, None, None), private=True)
        self.addCleanup(delete, browser)

        def renderer(tab):
            view = QWidget(tab)
            view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            view.url = Mock(return_value=QUrl())
            view.setUrl = lambda url: setattr(view.url, 'return_value', QUrl(url))
            view.page = Mock()
            view.history = Mock()
            browser.remove_placeholder(tab)
            tab.view = view
            tab.layout_.addWidget(view)
            return view

        browser.make_view = renderer
        browser.show()
        self.app.processEvents()
        return browser

    def test_keyboard_reopens_tabs_newest_first_and_restores_position(self):
        browser = self.make_browser()
        left = browser.tabs.currentWidget()
        browser.open_url(left, QUrl('https://example.org/left'))
        browser.add_tab(QUrl('https://example.org/middle'))
        right = browser.add_tab(QUrl('https://example.org/right'))
        browser.close_tab(1)
        browser.close_tab(0)
        self.assertIs(browser.tabs.currentWidget(), right)
        for expected in ('left', 'middle'):
            QTest.keyClick(browser.tabs.currentWidget().view, Qt.Key.Key_T,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(browser.tabs.currentWidget().view.url().path(), f'/{expected}')
        self.assertEqual([browser.tabs.widget(i).view.url().path() for i in range(3)],
                         ['/left', '/middle', '/right'])

    def test_last_page_uses_empty_tab_without_leaking_to_another_window(self):
        browser = self.make_browser()
        browser.open_url(browser.tabs.currentWidget(), QUrl('https://example.org/last'))
        browser.close_tab(0)
        placeholder = browser.tabs.currentWidget()
        self.assertIsNone(placeholder.view)
        other = self.make_browser()
        other.reopen_tab()
        self.assertIsNone(other.tabs.currentWidget().view)
        self.assertEqual(other.status.text(), 'No closed tabs to reopen.')
        browser.reopen_tab()
        self.assertIs(browser.tabs.currentWidget(), placeholder)
        self.assertEqual(browser.tabs.count(), 1)
        self.assertEqual(placeholder.view.url().path(), '/last')

    def test_blank_and_unsupported_addresses_are_skipped(self):
        browser = self.make_browser()
        browser.close_tab(0)
        tab = browser.tabs.currentWidget()
        browser.make_view(tab).setUrl(QUrl('file:///tmp/example'))
        browser.close_tab(0)
        browser.reopen_tab()
        self.assertIsNone(browser.tabs.currentWidget().view)
        self.assertEqual(browser.status.text(), 'No closed tabs to reopen.')

    def test_unvisited_restored_tab_can_be_reopened(self):
        browser = self.make_browser()
        first = browser.tabs.currentWidget()
        restored = browser.add_tab(QUrl('https://example.org/deferred'), foreground=False, deferred=True)
        self.assertIsNone(restored.view)
        browser.close_tab(browser.tabs.indexOf(restored))
        browser.reopen_tab()
        self.assertIs(browser.tabs.currentWidget(), first)
        self.assertEqual(first.view.url().path(), '/deferred')

    def test_history_is_persistent_bounded_and_excludes_private_and_failed_pages(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'history.sqlite'
            history = VisitHistory(path)
            history.LIMIT = 2
            browser = self.make_browser()
            tab = browser.tabs.currentWidget()
            browser.open_url(tab, QUrl('https://example.org/private'))
            tab.view.title = Mock(return_value='Example')
            browser.loaded(tab, True)
            self.assertFalse(path.exists())
            browser.history_store = history  # Use the same fixture in public mode for disk effects.
            browser.open_url(tab, QUrl('https://example.org/failed'))
            browser.loaded(tab, False)
            self.assertFalse(path.exists())
            for name in ('oldest', 'previous', 'newest'):
                browser.open_url(tab, QUrl(f'https://example.org/{name}'))
                browser.loaded(tab, True)
            restored = VisitHistory(path)
            self.assertEqual([url.rsplit('/', 1)[-1] for url, _, _ in restored.rows()], ['newest', 'previous'])
            restored.forget('https://example.org/previous')
            self.assertEqual(len(restored.rows()), 1)
            restored.clear()
            self.assertEqual(restored.rows(), [])

    def test_narrow_address_reflows_and_themed_close_tracks_tab_after_reorder(self):
        browser = self.make_browser()
        browser.resize(470, 350)
        QTest.qWait(60)
        self.assertTrue(browser.narrow_toolbar)
        self.assertGreater(browser.address.width(), browser.width() * .8)
        first = browser.tabs.currentWidget()
        second = browser.add_tab()
        bar = browser.tabs.tabBar()
        bar.moveTab(1, 0)
        close = bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        self.assertEqual(close.objectName(), 'mellipiTabClose')
        self.assertFalse(close.icon().isNull())
        close.click()
        self.assertEqual(browser.tabs.indexOf(second), -1)
        self.assertIs(browser.tabs.currentWidget(), first)

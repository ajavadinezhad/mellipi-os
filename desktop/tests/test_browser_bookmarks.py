"""Verify local bookmark persistence and private-window isolation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from PyQt6.QtCore import QUrl

from mellipi_browser import Bookmarks, Browser


class BookmarkTests(TestCase):
    def test_add_and_remove_merge_across_windows(self):
        first, second = QUrl('https://example.org/a%20b'), QUrl('http://example.net/')
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bookmarks.json'
            a, b = Bookmarks(path), Bookmarks(path)
            self.assertTrue(a.toggle(first, 'First\n page'))
            self.assertTrue(b.toggle(second, 'Second'))
            self.assertEqual(a.read(), {'https://example.org/a%20b': 'First page',
                                        'http://example.net/': 'Second'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(a.toggle(first, 'First'))
            self.assertEqual(b.read(), {'http://example.net/': 'Second'})

    def test_unsafe_urls_and_indirect_or_invalid_storage(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bookmarks.json'
            store = Bookmarks(path)
            for value in ('file:///etc/hosts', 'javascript:alert(1)', 'https://me:secret@example.org/'):
                with self.assertRaises(ValueError):
                    store.toggle(QUrl(value), 'Unsafe')
            self.assertFalse(path.exists())
            target = path.with_name('target')
            target.write_text('not json')
            path.symlink_to(target)
            with self.assertRaises(OSError):
                store.toggle(QUrl('https://example.org/'), 'Title')
            path.unlink()
            path.write_text('not json')
            with self.assertRaises(ValueError):
                store.toggle(QUrl('https://example.org/'), 'Title')
            self.assertEqual(path.read_text(), 'not json')

    def test_bookmark_actions_do_not_read_private_pages(self):
        view = SimpleNamespace(bookmarks=None, bookmark_page=Mock(), message=Mock())
        Browser.toggle_bookmark(view)
        Browser.show_bookmarks(view)
        view.bookmark_page.assert_not_called()
        view.message.assert_not_called()

    def test_storage_cap_does_not_replace_existing_entries(self):
        with TemporaryDirectory() as tmp:
            store = Bookmarks(Path(tmp) / 'bookmarks.json')
            with patch.object(store, 'MAX_ITEMS', 1):
                store.toggle(QUrl('https://example.org/'), 'First')
                with self.assertRaises(ValueError):
                    store.toggle(QUrl('https://example.net/'), 'Second')
            self.assertEqual(store.read(), {'https://example.org/': 'First'})

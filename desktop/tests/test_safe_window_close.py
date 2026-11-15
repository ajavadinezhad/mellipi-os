"""Regression tests for ignored close requests and retryable logout."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from mellipi_files import Files
from session_exit import SessionExit


class SafeWindowCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        for _ in range(100):
            if predicate():
                return
            QTest.qWait(10)
        self.fail('Timed out waiting for close state')

    def test_empty_logout_completes_immediately_without_a_worker(self):
        review = SessionExit(lambda ident: self.fail(f'Unexpected close: {ident}'),
                             inhibitor_reader=lambda: self.fail('Logout should not query logind'))
        self.addCleanup(review.close)
        ready = []
        review.readyToExit.connect(lambda: ready.append(True))
        review.openReview()
        self.assertEqual(ready, [])
        review.closeAndWait()
        self.assertEqual(ready, [True])
        self.assertIsNone(review._pool)

    def test_unresponsive_window_leaves_review_retryable(self):
        calls = []
        review = SessionExit(calls.append)
        self.addCleanup(review.close)
        review.setWindows([{'id': '1', 'klass': 'mellipi-files', 'minimized': True}])
        review.openReview()
        review.closeAndWait()
        self.wait_for(lambda: calls == ['1'])
        review._closeTimedOut()
        self.assertTrue(review.state['active'])
        self.assertTrue(review.state['armed'])
        self.assertTrue(review.state['retry'])
        self.assertTrue(review.state['error'])
        review.closeAndWait()
        self.wait_for(lambda: calls == ['1', '1'])

    def test_files_finishes_operation_then_closes_without_second_request(self):
        release = Event()
        with TemporaryDirectory() as directory:
            window = Files(Path(directory))
            window.show()
            window.run_job(lambda: release.wait(3))
            try:
                self.assertFalse(window.close())
                self.assertTrue(window.isVisible())
            finally:
                release.set()
            self.wait_for(lambda: window not in self.application.topLevelWidgets())

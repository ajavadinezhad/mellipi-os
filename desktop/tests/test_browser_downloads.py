"""Exercise Browser's download lifecycle without a network or display."""
from enum import IntEnum
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from mellipi_browser import Browser


class Download(QObject):
    class DownloadState(IntEnum):
        DownloadRequested = 0
        DownloadInProgress = 1
        DownloadCompleted = 2
        DownloadCancelled = 3
        DownloadInterrupted = 4

    stateChanged = pyqtSignal(int)
    receivedBytesChanged = pyqtSignal()
    totalBytesChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.target_dir = '/tmp'
        self.filename = 'suggested.txt'
        self.current = self.DownloadState.DownloadRequested
        self.size = -1
        self.received = 0

    def state(self):
        return self.current

    def receivedBytes(self):
        return self.received

    def totalBytes(self):
        return self.size

    def interruptReasonString(self):
        return 'Connection lost'

    def downloadFileName(self):
        return self.filename

    def downloadDirectory(self):
        return self.target_dir

    def setDownloadFileName(self, value):
        self.filename = value

    def setDownloadDirectory(self, value):
        self.target_dir = value

    def to_state(self, state):
        self.current = state
        self.stateChanged.emit(state)

    def accept(self):
        self.to_state(self.DownloadState.DownloadInProgress)

    def cancel(self):
        self.to_state(self.DownloadState.DownloadCancelled)


class BrowserDownloadsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.sip import delete
        settings = SimpleNamespace(WebAttribute=Mock(), setAttribute=Mock())
        profile = Mock()
        profile.settings.return_value = settings
        self.browser = Browser((lambda *_: profile, None, None, None), private=True)
        self.addCleanup(delete, self.browser)
        self.browser.show()
        self.app.processEvents()

    def start(self, name='test.txt'):
        request = Download()
        with patch('mellipi_browser.FileChooser.getSaveFileName', return_value=(f'/tmp/{name}', '')):
            self.browser.download(request)
        return request

    def test_keyboard_progress_cancel_and_close_panel(self):
        request = self.start()
        self.assertEqual(request.filename, 'test.txt')
        self.browser.address.setFocus()
        QTest.keyClick(self.browser.address, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier)
        self.assertIs(self.browser.pages.currentWidget(), self.browser.download_page)
        self.assertIs(QApplication.focusWidget(), self.browser.download_close)
        row = self.browser.download_rows[0]
        self.assertEqual(row.progress.maximum(), 0)
        request.size = 4096
        request.received = 1024
        request.receivedBytesChanged.emit()
        self.assertEqual(row.progress.value(), 25)
        QTest.mouseClick(row.cancel_button, Qt.MouseButton.LeftButton)
        self.assertEqual(request.state(), Download.DownloadState.DownloadCancelled)
        self.assertTrue(row.finished)
        self.assertFalse(row.folder_button.isEnabled())
        self.assertTrue(row.progress.isHidden())
        QTest.keyClick(row, Qt.Key.Key_Escape)
        self.assertIs(self.browser.pages.currentWidget(), self.browser.tabs)
        self.assertIs(QApplication.focusWidget(), self.browser.address)

    def test_success_opens_containing_folder_and_failures_never_open_it(self):
        done = self.start('<b>report.txt')
        row = self.browser.download_rows[0]
        self.assertEqual(row.name.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(row.name.text(), '<b>report.txt')
        done.to_state(Download.DownloadState.DownloadCompleted)
        with patch('mellipi_browser.QDesktopServices.openUrl', return_value=True) as show:
            row.folder_button.click()
            self.assertEqual(show.call_args.args[0].toLocalFile(), '/tmp')
            failed = self.start()
            failed.to_state(Download.DownloadState.DownloadInterrupted)
            self.browser.download_rows[0].folder_button.click()
            show.assert_called_once()
        self.assertEqual(self.browser.download_rows[0].status.text(), 'Interrupted: Connection lost')

    def test_cancelled_save_and_duplicate_active_destination_do_not_create_rows(self):
        request = self.start()
        duplicate = self.start()
        self.assertEqual(request.state(), Download.DownloadState.DownloadInProgress)
        self.assertEqual(duplicate.state(), Download.DownloadState.DownloadCancelled)
        dismissed = Download()
        with patch('mellipi_browser.FileChooser.getSaveFileName', return_value=('', '')):
            self.browser.download(dismissed)
        self.assertEqual(dismissed.state(), Download.DownloadState.DownloadCancelled)
        self.assertEqual(len(self.browser.download_rows), 1)

    def test_close_keeps_downloads_until_explicitly_confirmed(self):
        request = self.start()
        with patch('mellipi_browser.themed_prompt', return_value=False) as prompt:
            self.assertFalse(self.browser.close())
            self.assertIs(prompt.call_args.args[0], self.browser)
        self.assertEqual(request.state(), Download.DownloadState.DownloadInProgress)
        with patch('mellipi_browser.themed_prompt', return_value=True):
            self.assertTrue(self.browser.close())
        self.assertEqual(request.state(), Download.DownloadState.DownloadCancelled)

from enum import Enum
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, QUrl

from mellipi_browser import Browser, capture_origin


class Permission(Enum):
    PermissionDeniedByUser = 1
    PermissionGrantedByUser = 2


class Page(QObject):
    PermissionPolicy = Permission

    def __init__(self):
        super().__init__()
        self.address = QUrl('https://meeting.example/room')
        self.setFeaturePermission = Mock()

    def url(self):
        return self.address


class BrowserPermissionTests(unittest.TestCase):
    def setUp(self):
        self.page, self.tab = Page(), object()
        self.browser = SimpleNamespace(tabs=SimpleNamespace(currentWidget=lambda: self.tab),
                                       isVisible=lambda: True, capture_prompt=None)
        self.browser.pages = SimpleNamespace(currentWidget=lambda: self.browser.tabs)
        self.origin = QUrl('https://meeting.example')
        self.feature = SimpleNamespace(name='MediaAudioVideoCapture')

    def request(self, origin=None, feature=None):
        Browser.request_capture(self.browser, self.tab, self.page, origin or self.origin,
                                feature or self.feature)

    def test_asks_and_grants_supported_access_on_explicit_confirmation(self):
        with patch('mellipi_browser.themed_prompt', return_value=True) as confirm:
            self.request()
        self.assertIn('https://meeting.example', confirm.call_args.args[2])
        self.assertIn('microphone and camera', confirm.call_args.args[2])
        self.page.setFeaturePermission.assert_called_once_with(
            self.origin, self.feature, Permission.PermissionGrantedByUser)

    def test_denies_unrelated_insecure_and_screen_capture_requests_without_prompt(self):
        with patch('mellipi_browser.themed_prompt') as confirm:
            self.request(QUrl('https://other.example'))
            self.request(QUrl('http://meeting.example'))
            self.request(feature=SimpleNamespace(name='DesktopVideoCapture'))
        confirm.assert_not_called()
        self.assertEqual(self.page.setFeaturePermission.call_count, 3)
        self.assertTrue(all(call.args[2] is Permission.PermissionDeniedByUser
                            for call in self.page.setFeaturePermission.call_args_list))

    def test_redirect_during_confirmation_cannot_receive_permission(self):
        def redirect(*_):
            self.page.address = QUrl('https://meeting.example/other-room')
            return True
        with patch('mellipi_browser.themed_prompt', side_effect=redirect):
            self.request()
        self.page.setFeaturePermission.assert_called_once_with(
            self.origin, self.feature, Permission.PermissionDeniedByUser)

    def test_origin_compares_explicit_port_and_rejects_credentials(self):
        self.assertEqual(capture_origin(QUrl('https://meeting.example:443/a')),
                         capture_origin(self.origin))
        self.assertNotEqual(capture_origin(QUrl('https://meeting.example:8443')),
                            capture_origin(self.origin))
        self.assertIsNone(capture_origin(QUrl('https://name@meeting.example')))

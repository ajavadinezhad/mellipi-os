from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from native_app import Bridge
from system_services import SystemServices


class NotificationFallbackTest(TestCase):
    def test_click_without_default_action_restores_matching_window(self):
        note = dict(id=1, app='Fixture', desktopEntry='org.example.Fixture', actions=[])
        bridge = SimpleNamespace(
            _apps=[dict(id='org.example.Fixture.desktop', name='Fixture')],
            _windows=[dict(id='17', klass='org.example.fixture', minimized=True)],
            focusWindow=Mock(), launch=Mock(), notify=Mock(),
        )
        service = SystemServices(enabled=False)
        self.addCleanup(service.close)
        service.openNotification.connect(lambda n: Bridge.openNotification(bridge, n))
        service.receiveNotification(note)
        service.activateNotification(1)
        bridge.focusWindow.assert_called_once_with('17')
        bridge.launch.assert_not_called()

    def test_click_without_open_window_launches_registered_desktop_entry(self):
        bridge = SimpleNamespace(
            _apps=[dict(id='org.example.Fixture.desktop', name='Fixture')],
            _windows=[], focusWindow=Mock(), launch=Mock(), notify=Mock(),
        )
        Bridge.openNotification(bridge, dict(app='Fixture', desktopEntry='org.example.Fixture'))
        bridge.launch.assert_called_once_with('org.example.Fixture.desktop')
        bridge.focusWindow.assert_not_called()

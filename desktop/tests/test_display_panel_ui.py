"""Display draft presentation tests; never talk to an output backend."""
import unittest
from pathlib import Path

from display_config import catalog
from native_app import Icons
from qt_compat import QObject, Property, QQmlApplicationEngine, QUrl, Signal, Slot, QT5, QT6_WAYLAND
from test_system_settings_ui import QApplication, Orbit, QQmlComponent

if QT5:
    from PyQt5.sip import delete
elif QT6_WAYLAND:
    from PyQt6.sip import delete
else:
    from shiboken6 import delete


class DisplayControls(QObject):
    changed = Signal()

    outputs = Property('QVariantList', lambda _self: catalog([
        dict(name='HDMI-A-1', active=True, current_mode=dict(width=3240, height=1356, refresh=60000),
             modes=[dict(width=2560, height=1080, refresh=75000), dict(width=3280, height=1376, refresh=57000)]),
        dict(name='DP-1', model='Second monitor', active=True,
             current_mode=dict(width=1920, height=1080, refresh=60000)),
    ]), notify=changed)
    state = Property('QVariantMap', lambda _self: dict(
        available=True, busy=False, pending=False, error=''), notify=changed)

    @Slot()
    def refresh(self):
        pass


class DisplayPanelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_compact_panel_previews_effective_size_and_keeps_connector_unambiguous(self):
        orbit, displays = Orbit(), DisplayControls()
        engine = QQmlApplicationEngine()
        engine.addImageProvider('icons', Icons())
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
        engine.rootContext().setContextProperty('Orbit', orbit)
        engine.rootContext().setContextProperty('DisplayControls', displays)
        source = Path(__file__).resolve().parents[1] / 'native/DisplayPanel.qml'
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(source)))
        panel = component.create()
        self.addCleanup(delete, engine)
        self.addCleanup(delete, component)
        self.assertIsNotNone(panel, [e.toString() for e in component.errors()])
        self.addCleanup(delete, panel)
        # QML context properties are only valid while the fixture objects live.
        self.fixture = orbit, displays
        panel.setProperty('width', 320)
        panel.setProperty('height', 340)
        self.app.processEvents()
        toggle = panel.findChild(QObject, 'displayOutputPickerToggle')
        summary = panel.findChild(QObject, 'displayEffectiveSize')
        picker = panel.findChild(QObject, 'displayModePicker')
        mode_toggle = panel.findChild(QObject, 'displayModePickerToggle')
        self.assertIn('Current custom mode', mode_toggle.property('text'))
        self.assertEqual(picker.property('devices').toVariant()[0]['name'], '2560x1080@75.000Hz')
        self.assertEqual(len(picker.property('devices').toVariant()), 1)
        self.assertEqual(toggle.property('text'), 'HDMI-A-1')
        self.assertIn('3240 × 1356', summary.property('text'))
        panel.setProperty('chosenScale', 1.25)
        panel.setProperty('chosenTransform', '270')
        self.app.processEvents()
        self.assertIn('1085 × 2592', summary.property('text'))
        self.assertEqual(warnings, [])

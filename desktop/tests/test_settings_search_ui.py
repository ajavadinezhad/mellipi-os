"""Exercise the Settings search, keyboard flow, and allowlisted results in QML."""
from pathlib import Path
import unittest

from action_targets import setting_actions
from qt_compat import QApplication, QObject, Property, QQmlApplicationEngine, QUrl, Qt, Signal, Slot, QT5, QT6_WAYLAND

if QT5:
    from PyQt5.QtQml import QQmlComponent
    from PyQt5.QtTest import QTest
    from PyQt5.sip import delete
elif QT6_WAYLAND:
    from PyQt6.QtQml import QQmlComponent
    from PyQt6.QtTest import QTest
    from PyQt6.sip import delete
else:
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtTest import QTest
    from shiboken6 import delete

NATIVE = Path(__file__).resolve().parents[1] / 'native'

class DisplayFixture(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.pending = False
        self.reverted = False

    state = Property('QVariantMap', lambda self: dict(pending=self.pending, busy=False,
                                                       secondsRemaining=12), notify=changed)

    @Slot()
    def revert(self):
        self.reverted = True
        self.pending = False
        self.changed.emit()


class OrbitFixture(QObject):
    def __init__(self):
        super().__init__()
        self.activated = []

    appearance = Property('QVariantMap', lambda self: dict(
        shellLayout='fold', density='compact', reducedMotion=True,
        corners='soft', textScale=1.5), constant=True)
    compact = Property(bool, lambda self: True, constant=True)
    economy = Property(bool, lambda self: True, constant=True)
    themeMode = Property(str, lambda self: 'dark', constant=True)
    accentColor = Property(str, lambda self: '#b8d893', constant=True)
    settingsSection = Property(int, lambda self: 12, constant=True)
    systemActions = Property('QVariantList', lambda self: [
        *setting_actions(),
        dict(id='shutdown', name='Shut down', searchText='brightness shutdown', destination='action:shutdown'),
    ], constant=True)

    interactionChanged = Signal()

    @Slot(str)
    def activateSystemAction(self, action):
        self.activated.append(action)

    @Slot(QObject, str, float, float)
    def queueItemTooltip(self, *_):
        pass

    @Slot()
    def hideTooltip(self):
        pass


class SettingsSearchTests(unittest.TestCase):
    def test_keyboard_search_opens_only_the_setting_and_escape_clears(self):
        from native_app import Icons

        app = QApplication.instance() or QApplication([])
        self.orbit = OrbitFixture()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit', self.orbit)
        displays = DisplayFixture()
        engine.rootContext().setContextProperty('DisplayControls', displays)
        engine.addImageProvider('icons', Icons())
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
        component = QQmlComponent(engine)
        component.setData(b'''
            import QtQuick 2.15
            import QtQuick.Window 2.15
            import "."
            Window { width: 480; height: 420; visible: true
                SystemPanel { anchors.fill: parent }
            }
        ''', QUrl.fromLocalFile(str(NATIVE / 'settings-search-fixture.qml')))
        window = component.create()
        try:
            self.assertIsNotNone(window, [e.toString() for e in component.errors()])
            window.requestActivate()
            QTest.qWait(50)
            search = window.findChild(QObject, 'settingsSearchField')
            panel = window.findChild(QObject, 'systemSettingsPanel')
            results = window.findChild(QObject, 'settingsSearchResults')
            self.assertIsNotNone(search)
            section_picker = window.findChild(QObject, 'settingsPageChoice')
            sidebar = window.findChild(QObject, 'systemSettingsIndex')
            viewport = window.findChild(QObject, 'settingsContentViewport')
            self.assertTrue(section_picker.property('visible'))
            self.assertFalse(sidebar.property('visible'))
            self.assertGreaterEqual(viewport.property('width'), 475)
            QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            self.assertTrue(search.property('activeFocus'))
            displays.pending = True
            displays.changed.emit()
            QTest.qWait(20)
            confirmation = window.findChild(QObject, 'displayConfirmation')
            revert = window.findChild(QObject, 'displayRevert')
            self.assertTrue(confirmation.property('visible'))
            self.assertTrue(revert.property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            search.setProperty('text', 'brightness')
            QTest.qWait(20)
            rows = panel.property('searchResults')
            names = [row['name'] for row in (rows.toVariant() if hasattr(rows, 'toVariant') else rows)]
            self.assertEqual(names, ['Display brightness'])
            self.assertNotIn('Shut down', names)
            self.assertTrue(confirmation.property('visible'))
            revert.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Return)
            self.assertTrue(displays.reverted)
            self.assertFalse(confirmation.property('visible'))
            QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            search.setProperty('text', 'USB recording')
            QTest.qWait(20)
            self.assertEqual(results.property('count'), 1)
            QTest.keyClick(window, Qt.Key.Key_Down)
            self.assertTrue(results.property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Return)
            self.assertEqual(self.orbit.activated, ['microphone'])
            self.assertEqual(search.property('text'), '')
            QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            for query, expected in (
                ('motion', 'Desktop animations'), ('text size', 'Desktop text size'),
                ('high contrast', 'High contrast'), ('quick settings', 'Arrange Quick Settings'),
                ('arrange controls', 'Arrange Quick Settings'),
            ):
                search.setProperty('text', query)
                rows = panel.property('searchResults')
                self.assertEqual([row['name'] for row in rows.toVariant()], [expected], query)
            search.setProperty('text', 'no such setting')
            self.assertEqual(results.property('count'), 0)
            QTest.keyClick(window, Qt.Key.Key_Escape)
            self.assertEqual(search.property('text'), '')
            window.setWidth(640)
            QTest.qWait(50)
            self.assertTrue(section_picker.property('visible'))
            self.assertGreaterEqual(viewport.property('width'), 610)
            window.setWidth(820)
            QTest.qWait(50)
            self.assertFalse(section_picker.property('visible'))
            self.assertTrue(sidebar.property('visible'))
            self.assertLess(viewport.property('width'), 820)
            self.assertGreaterEqual(viewport.property('width'), 620)
            self.assertLessEqual(sidebar.property('width'), 184)
            self.assertGreater(viewport.property('x'), sidebar.property('x') + sidebar.property('width'))
            self.assertEqual(search.property('width'), sidebar.property('width'))
            self.assertGreaterEqual(sidebar.property('y'), search.property('height'))
            self.assertEqual(warnings, [])
        finally:
            if window:
                window.close()
                delete(window)
            delete(component)
            delete(engine)


if __name__ == '__main__':
    unittest.main()

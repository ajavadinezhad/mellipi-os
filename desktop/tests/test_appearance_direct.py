"""Appearance controls save directly through the settings owner."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from PyQt6.QtCore import QMetaObject, QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtQuick import QQuickItem

from native_app import Bridge, Icons
from preferences import Preferences
from qt_compat import QApplication, QQmlApplicationEngine
from test_settings_search_ui import NATIVE, OrbitFixture, QQmlComponent, QTest, delete
from theme_catalog import presets


class AppearanceFixture(OrbitFixture):
    changed = pyqtSignal()

    def __init__(self, preferences):
        super().__init__()
        self.preferences = preferences
        self.saves = []
        self.notices = []

    appearance = pyqtProperty('QVariantMap', lambda s: s.preferences.appearance(), notify=changed)
    themePresets = pyqtProperty('QVariantList', lambda s: presets(), constant=True)
    accentPresets = pyqtProperty('QVariantList', lambda s: [], constant=True)
    isWayland = pyqtProperty(bool, lambda s: True, constant=True)
    nativeCompositor = pyqtProperty(bool, lambda s: True, constant=True)
    nativePaletteSupported = pyqtProperty(bool, lambda s: True, constant=True)
    nativeSnapSupported = pyqtProperty(bool, lambda s: True, constant=True)
    outputs = pyqtProperty('QVariantList', lambda s: [], constant=True)

    @pyqtSlot('QVariantMap')
    def applyAppearance(self, changes):
        self.saves.append(changes)
        self.settingsChanged = self.changed
        Bridge.applyAppearance(self, changes)

    @pyqtSlot(str)
    def applyTheme(self, theme):
        self.settingsChanged = self.changed
        Bridge.applyTheme(self, theme)

    def notify(self, message):
        self.notices.append(message)

    def applyWindowTheme(self):
        pass


class AppearanceSettingsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_direct_save_is_atomic_and_appearance_fits_narrow_windows(self):
        with TemporaryDirectory() as tmp:
            preferences = Preferences(Path(tmp) / 'appearance.json')
            orbit = AppearanceFixture(preferences)
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty('Orbit', orbit)
            engine.addImageProvider('icons', Icons())
            warnings = []
            engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
            component = QQmlComponent(engine)
            component.setData(b'''
                import QtQuick 2.15
                import QtQuick.Window 2.15
                import "."
                Window {
                    width: 520; height: 520; visible: true
                    function chooseDune() { Orbit.applyTheme("dune"); }
                    function changeTaskbar() { studio.setValue("panelPosition","bottom"); }
                    function changeMode() { studio.setMode("black"); }
                    function enableContrast() { studio.setValue("highContrast",true); }
                    function invalidColor() { studio.setValue("accent","nothex"); }
                    function returnToDune() { Orbit.applyTheme("dune"); }
                    AppearancePanel { id: studio; anchors.fill: parent }
                }
            ''', QUrl.fromLocalFile(str(NATIVE / 'appearance-studio-fixture.qml')))
            window = component.create()
            try:
                self.assertIsNotNone(window, [e.toString() for e in component.errors()])
                QTest.qWait(35)
                studio = window.findChild(QObject, 'appearancePanel')
                for name in ('appearancePreview', 'appearanceApply', 'appearanceDiscard'):
                    self.assertIsNone(window.findChild(QQuickItem, name))
                self.assertFalse(preferences.path.exists())
                QMetaObject.invokeMethod(window, 'chooseDune')
                self.assertEqual(Preferences(preferences.path).values['themePreset'], 'dune')
                QMetaObject.invokeMethod(window, 'enableContrast')
                QMetaObject.invokeMethod(window, 'changeTaskbar')
                QMetaObject.invokeMethod(window, 'changeMode')
                self.assertEqual(orbit.saves[-1], {'mode': 'dark', 'darkLevel': 'black'})
                values = Preferences(preferences.path).values
                self.assertEqual((values['themePreset'], values['panelPosition']), ('custom', 'bottom'))
                self.assertFalse(values['highContrast'])
                QMetaObject.invokeMethod(window, 'returnToDune')
                values = Preferences(preferences.path).values
                self.assertTrue(values['highContrast'])
                self.assertEqual(values['panelPosition'], 'bottom')
                saved = preferences.path.read_bytes()
                QMetaObject.invokeMethod(window, 'invalidColor')
                orbit.applyAppearance({'themePreset': 'forest', 'pins': ['foo.desktop']})
                for width in (900, 290):
                    window.setWidth(width)
                    QTest.qWait(35)
                    self.assertLessEqual(studio.property('contentWidth'), width)
                    self.assertTrue(window.findChild(QQuickItem, 'themeModeSegments').isVisible())
                self.assertEqual(preferences.path.read_bytes(), saved)
                orbit.applyAppearance({'textScale': 1.2})
                QTest.qWait(35)
                picker = window.findChild(QQuickItem, 'appearanceTextScaleToggle')
                self.assertEqual(picker.property('text'), '120%')
                saved = preferences.path.read_bytes()
                self.assertTrue(QMetaObject.invokeMethod(picker, 'clicked') is None)
                self.assertEqual(preferences.path.read_bytes(), saved)
                window.close()
                self.assertTrue(orbit.notices)
                self.assertEqual(warnings, [])
            finally:
                if window:
                    window.close()
                    delete(window)
                delete(component)
                delete(engine)

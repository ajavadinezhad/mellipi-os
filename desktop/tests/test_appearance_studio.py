"""The native preview uses a local draft, while Apply writes once to the settings owner."""
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
    def applyAppearance(self, draft):
        self.saves.append(draft)
        self.settingsChanged = self.changed
        Bridge.applyAppearance(self, draft)

    def notify(self, message):
        self.notices.append(message)

    def applyWindowTheme(self):
        pass


class AppearanceStudioTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_scope_apply_and_narrow_reflow(self):
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
                    function stageStudio() {
                        studio.selectTheme("dune");
                        studio.stage("panelPosition","bottom");
                        studio.stage("textScale",1.5);
                    }
                    function discardStudio() { studio.discard(); }
                    function commitStudio() { studio.commit(); }
                    function togglePreview() {studio.compactPreviewOpen=!studio.compactPreviewOpen;}
                    AppearancePanel { id: studio; anchors.fill: parent }
                }
            ''', QUrl.fromLocalFile(str(NATIVE / 'appearance-studio-fixture.qml')))
            window = component.create()
            try:
                self.assertIsNotNone(window, [e.toString() for e in component.errors()])
                QTest.qWait(35)
                studio = window.findChild(QObject, 'appearancePanel')
                preview = window.findChild(QQuickItem, 'appearancePreview')
                self.assertTrue(preview.isVisible())
                QMetaObject.invokeMethod(window, 'stageStudio')
                self.assertTrue(studio.property('dirty'))
                self.assertEqual(preview.property('wallpaper'), 'theme-dune')
                self.assertEqual(preview.property('taskbarPosition'), 'bottom')
                self.assertEqual(preview.property('textScale'), 1.5)
                self.assertEqual(orbit.saves, [])
                self.assertFalse(preferences.path.exists())
                QMetaObject.invokeMethod(window, 'discardStudio')
                self.assertFalse(studio.property('dirty'))
                self.assertEqual(preview.property('wallpaper'), 'auto')
                QMetaObject.invokeMethod(window, 'stageStudio')
                QMetaObject.invokeMethod(window, 'commitStudio')
                self.assertEqual(len(orbit.saves), 1)
                self.assertEqual(Preferences(preferences.path).values['themePreset'], 'dune')
                self.assertEqual(Preferences(preferences.path).values['panelPosition'], 'bottom')
                self.assertFalse(studio.property('dirty'))
                saved = preferences.path.read_bytes()
                orbit.applyAppearance({'themePreset': 'forest', 'pins': ['foo.desktop']})
                self.assertEqual(preferences.path.read_bytes(), saved)
                self.assertTrue(orbit.notices)
                window.setWidth(900)
                QTest.qWait(35)
                self.assertTrue(studio.property('sidePreview'))
                self.assertGreater(window.findChild(QQuickItem, 'appearanceStudio').x(), 300)
                window.setWidth(290)
                QTest.qWait(35)
                self.assertFalse(studio.property('showPreview'))
                QMetaObject.invokeMethod(window, 'togglePreview')
                QTest.qWait(35)
                self.assertTrue(window.findChild(QQuickItem, 'appearancePreview').isVisible())
                self.assertEqual(warnings, [])
            finally:
                if window:
                    window.close()
                    delete(window)
                delete(component)
                delete(engine)

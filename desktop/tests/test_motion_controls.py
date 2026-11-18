"""Real Qt motion feedback with independently configurable policies."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from PyQt6.QtCore import QMetaObject, QUrl, Qt
from PyQt6.QtQuick import QQuickItem

from native_app import Icons
from preferences import Preferences
from qt_compat import QApplication, QQmlApplicationEngine
from test_appearance_direct import AppearanceFixture
from test_settings_search_ui import NATIVE, QQmlComponent, QTest, delete


class MotionControlsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reduce_motion_snaps_feedback_and_preserves_category_choices(self):
        with TemporaryDirectory() as tmp:
            preferences = Preferences(Path(tmp) / 'settings.json')
            preferences.update({'profile': 'balanced', 'controlMotion': False, 'motionPace': 'relaxed'})
            orbit = AppearanceFixture(preferences)
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty('Orbit', orbit)
            engine.addImageProvider('icons', Icons())
            warnings = []
            engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
            component = QQmlComponent(engine)
            component.setData(b'''
                import QtQuick 2.15
                import QtQuick.Window 2.15
                import "."
                Window {
                    width: 410; height: 520; visible: true
                    property int duration: Theme.desktopMotion
                    property int controlsDuration: Theme.motion
                    property int panelsDuration: Theme.panelMotion
                    property real selection: animated.value
                    property real taskTarget: 0
                    function selectTask() {taskTarget=1;}
                    function deselectTask() {taskTarget=0;}
                    function allow() {panel.setValue("reducedMotion",false);}
                    function disableDesktopFade() {panel.setValue("desktopMotion",false);}
                    MotionValue {id:animated;target:taskTarget;duration:Theme.desktopMotion}
                    AppearancePanel {id:panel;section:2;anchors.fill:parent}
                }
            ''', QUrl.fromLocalFile(str(NATIVE / 'motion-controls-fixture.qml')))
            window = component.create()
            try:
                self.assertIsNotNone(window, [row.toString() for row in component.errors()])
                QTest.qWait(30)
                self.assertGreater(window.property('duration'), 0)
                self.assertEqual(window.property('controlsDuration'), 0)
                self.assertGreater(window.property('panelsDuration'), 0)
                self.assertFalse(window.findChild(QQuickItem, 'motionDesktopToggle').isVisible())
                window.findChild(QQuickItem, 'motionCustomize').forceActiveFocus()
                QTest.keyClick(window, Qt.Key.Key_Return)
                self.assertTrue(window.findChild(QQuickItem, 'motionDesktopToggle').isVisible())
                QMetaObject.invokeMethod(window, 'selectTask')
                self.assertEqual(window.property('selection'), 0)
                master = window.findChild(QQuickItem, 'motionReduceToggle')
                self.assertIsNotNone(master)
                master.forceActiveFocus()
                QTest.keyClick(window, Qt.Key.Key_Space)
                self.assertTrue(preferences.values['reducedMotion'])
                self.assertEqual(window.property('selection'), 1)
                self.assertEqual(window.property('duration'), 0)
                self.assertEqual(window.property('panelsDuration'), 0)
                for name in ('motionDesktopToggle', 'motionControlsToggle', 'motionWindowToggle',
                             'motionPanelToggle', 'motionPaceSegments', 'motionWorkspaceToggle'):
                    control = window.findChild(QQuickItem, name)
                    self.assertIsNotNone(control, name)
                    self.assertTrue(control.isVisible(), name)
                    self.assertFalse(control.isEnabled(), name)
                self.assertTrue(window.findChild(QQuickItem, 'motionReduceToggle').isEnabled())
                QMetaObject.invokeMethod(window, 'deselectTask')
                self.assertEqual(window.property('selection'), 0)
                QMetaObject.invokeMethod(window, 'allow')
                self.assertEqual(window.property('controlsDuration'), 0)
                self.assertGreater(window.property('duration'), 0)
                QMetaObject.invokeMethod(window, 'selectTask')
                QMetaObject.invokeMethod(window, 'disableDesktopFade')
                self.assertEqual(window.property('selection'), 1)
                self.assertGreater(window.property('panelsDuration'), 0)
                self.assertEqual(Preferences(preferences.path).values['motionPace'], 'relaxed')
                self.assertEqual(warnings, [])
            finally:
                if window:
                    window.close()
                    delete(window)
                delete(component)
                delete(engine)

    def test_motion_preferences_reject_unsupported_values(self):
        for key in ('panelMotion', 'controlMotion', 'desktopMotion', 'windowMotion'):
            self.assertTrue(Preferences.validate(key, True))
            with self.assertRaises(ValueError):
                Preferences.validate(key, 1)
        with self.assertRaises(ValueError):
            Preferences.validate('motionPace', 'too-fast')

    def test_reset_appearance_preserves_accessibility_motion_override(self):
        with TemporaryDirectory() as tmp:
            preferences = Preferences(Path(tmp) / 'settings.json')
            preferences.update({'reducedMotion': True, 'controlMotion': False})
            preferences.reset_appearance()
            values = Preferences(preferences.path).values
            self.assertTrue(values['reducedMotion'])
            self.assertTrue(values['controlMotion'])

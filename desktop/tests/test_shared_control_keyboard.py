"""Keyboard and visual-state checks for the shared Qt Quick controls."""
import unittest

from qt_compat import QApplication, QObject, Property, QQmlApplicationEngine, QUrl, Qt
from test_settings_search_ui import NATIVE, OrbitFixture, QQmlComponent, QTest, delete
from test_system_settings_ui import QMetaObject


class HighContrastOrbit(OrbitFixture):
    appearance = Property('QVariantMap', lambda self: dict(
        shellLayout='fold', density='compact', reducedMotion=True,
        corners='soft', textScale=1.5, highContrast=True), constant=True)
    accentColor = Property(str, lambda self: '#777777', constant=True)


class SharedControlKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_keyboard_focus_and_selection_across_shared_controls(self):
        orbit = HighContrastOrbit()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit', orbit)
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
        component = QQmlComponent(engine)
        component.setData(b"""
            import QtQuick 2.15
            import QtQuick.Layouts 1.15
            import QtQuick.Window 2.15
            import "."
            Window {
                width: 320; height: 420; visible: true
                function focusSegments() { segments.focusSelection(); }
                function focusChoice() { combo.forceActiveFocus(); }
                function focusPicker() { picker.children[0].forceActiveFocus(); }
                function focusField() { field.forceActiveFocus(); }
                function focusPrimary() { primary.forceActiveFocus(); }
                ColumnLayout {
                    anchors.fill: parent
                    SettingsSegments {
                        id: segments;objectName:"segments";value:0
                        options: [{label:"One",value:0},{label:"Two",value:1},{label:"Three",value:2}]
                        onSelected: option => value=option
                    }
                    SettingsChoice {
                        id: combo;objectName:"choice";popupObjectName:"choicePopup"
                        model:["North","South","East"];currentIndex:0
                    }
                    AudioDevicePicker {
                        id: picker;objectName:"audio";selectedName:"speaker"
                        devices: [{name:"speaker",description:"Speaker"},
                                  {name:"old",description:"Unplugged",available:false},
                                  {name:"headset",description:"Headset"}]
                        onToggled: expanded=!expanded
                        onSelected: name => { selectedName=name; expanded=false; }
                    }
                    OrbitField {id:field;objectName:"field";placeholderText:"Find"}
                    OrbitButton {
                        id:primary;objectName:"primary";text:"Apply";accent:true
                        readonly property real labelContrast: Theme.contrast(
                            Theme.luminance(background.color), Theme.luminance(primaryInk))
                        readonly property int outline: background.border.width
                    }
                }
            }
        """, QUrl.fromLocalFile(str(NATIVE / 'shared-control-fixture.qml')))
        window = component.create()
        try:
            self.assertIsNotNone(window, [e.toString() for e in component.errors()])
            window.requestActivate()
            QTest.qWait(50)
            segments = window.findChild(QObject, 'segments')
            combo = window.findChild(QObject, 'choice')
            popup = window.findChild(QObject, 'choicePopup')
            picker = window.findChild(QObject, 'audio')
            field = window.findChild(QObject, 'field')
            primary = window.findChild(QObject, 'primary')

            QMetaObject.invokeMethod(window, 'focusSegments')
            QTest.keyClick(window, Qt.Key.Key_Right)
            self.assertEqual(segments.property('value'), 0)
            QTest.keyClick(window, Qt.Key.Key_Return)
            self.assertEqual(segments.property('value'), 1)
            QTest.keyClick(window, Qt.Key.Key_End)
            QTest.keyClick(window, Qt.Key.Key_Space)
            self.assertEqual(segments.property('value'), 2)

            QMetaObject.invokeMethod(window, 'focusChoice')
            self.assertTrue(combo.property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_Space)
            self.assertTrue(popup.property('visible'))
            QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.keyClick(window, Qt.Key.Key_Return)
            self.assertEqual(combo.property('currentIndex'), 1)
            self.assertFalse(popup.property('visible'))
            QTest.keyClick(window, Qt.Key.Key_Space)
            QTest.keyClick(window, Qt.Key.Key_Escape)
            self.assertFalse(popup.property('visible'))

            QMetaObject.invokeMethod(window, 'focusPicker')
            QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.qWait(20)
            self.assertTrue(picker.property('expanded'))
            QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.keyClick(window, Qt.Key.Key_Return)
            self.assertEqual(picker.property('selectedName'), 'headset')
            self.assertFalse(picker.property('expanded'))

            QMetaObject.invokeMethod(window, 'focusField')
            self.assertTrue(field.property('activeFocus'))
            QTest.keyClick(window, Qt.Key.Key_X)
            self.assertEqual(field.property('text'), 'x')
            self.assertTrue(field.property('background').property('focused'))
            QMetaObject.invokeMethod(window, 'focusPrimary')
            self.assertEqual(primary.property('outline'), 2)
            self.assertGreaterEqual(primary.property('labelContrast'), 4.5)
            QTest.keyPress(window, Qt.Key.Key_Space)
            self.assertTrue(primary.property('visuallyDown'))
            self.assertGreaterEqual(primary.property('labelContrast'), 4.5)
            QTest.keyRelease(window, Qt.Key.Key_Space)
            self.assertEqual(warnings, [])
        finally:
            if window is not None:
                delete(window)
            delete(component)
            delete(engine)

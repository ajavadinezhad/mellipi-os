"""Exercise shared QML settings controls at large text on a narrow viewport."""
import unittest

from qt_compat import QApplication, QObject, QQmlApplicationEngine, QUrl
from test_settings_search_ui import NATIVE, OrbitFixture, QQmlComponent, QTest, delete


class ShellControlLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_narrow_row_wraps_label_and_keeps_all_controls_inside(self):
        orbit = OrbitFixture()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit', orbit)
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(r.toString() for r in rows))
        component = QQmlComponent(engine)
        component.setData(b"""
            import QtQuick 2.15
            import QtQuick.Layouts 1.15
            import "."
            ColumnLayout {
                width: 208
                SettingRow {
                    objectName: "row"
                    label: "Remember the desktop appearance"
                    SettingsSegments {
                        id: segments
                        objectName: "segments"
                        value: "compact"
                        segmentWidth: 82
                        options: [{label:"Comfortable",value:"normal"},
                                  {label:"Compact",value:"compact"},
                                  {label:"Extra compact",value:"extra"}]
                    }
                }
                OrbitField {
                    objectName: "field"
                    text: "Editable settings value"
                    Layout.fillWidth: true
                    implicitHeight: 28
                }
            }
        """, QUrl.fromLocalFile(str(NATIVE / 'shell-control-layout-fixture.qml')))
        root = component.create()
        try:
            self.assertIsNotNone(root, [e.toString() for e in component.errors()])
            QTest.qWait(30)
            row = root.findChild(QObject, 'row')
            label = root.findChild(QObject, 'settingRowLabel')
            segments = root.findChild(QObject, 'segments')
            selection = root.findChild(QObject, 'segmentSelection')
            field = root.findChild(QObject, 'field')
            self.assertTrue(row.property('stacked'))
            self.assertGreater(label.property('lineCount'), 1)
            self.assertLessEqual(segments.property('width'), row.property('width') - 9)
            self.assertLessEqual(selection.property('x') + selection.property('width'), segments.property('width'))
            self.assertGreater(field.property('height'), 28)
            self.assertGreaterEqual(
                field.property('height'),
                field.property('contentHeight') + field.property('topPadding') + field.property('bottomPadding'),
            )
            root.setProperty('width', 800)
            QTest.qWait(30)
            self.assertFalse(row.property('stacked'))
            self.assertEqual(label.property('lineCount'), 1)
            self.assertEqual(warnings, [])
        finally:
            if root is not None:
                delete(root)
            delete(component)
            delete(engine)

    def test_switch_column_aligns_even_when_only_one_row_stacks(self):
        from PyQt6.QtCore import QPointF
        from PyQt6.QtQuick import QQuickItem
        orbit = OrbitFixture()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit', orbit)
        component = QQmlComponent(engine)
        component.setData(b"""
            import QtQuick 2.15
            import QtQuick.Layouts 1.15
            import "."
            ColumnLayout {
                width: 226
                SettingsGroup {
                    title: "Appearance"
                    SettingRow {
                        label: "High contrast"
                        SettingToggle { objectName: "firstSwitch" }
                    }
                }
                SettingsGroup {
                    title: "Connections"
                    SettingRow {
                        objectName: "auxiliaryRow"
                        label: "A longer label for a connected device"
                        OrbitButton { text: "Device details"; implicitWidth: 134 }
                        SettingToggle { objectName: "secondSwitch"; checked: true }
                    }
                    SettingRow {
                        label: "Bluetooth"
                        SettingToggle { objectName: "thirdSwitch"; enabled: false }
                    }
                }
            }
        """, QUrl.fromLocalFile(str(NATIVE / 'switch-column-fixture.qml')))
        root = component.create()
        try:
            self.assertIsNotNone(root, [e.toString() for e in component.errors()])
            for width, stacked in ((226, True), (640, False), (226, True)):
                root.setProperty('width', width)
                QTest.qWait(50)
                row = root.findChild(QObject, 'auxiliaryRow')
                self.assertEqual(row.property('stacked'), stacked)
                switches = [root.findChild(QQuickItem, name + 'Switch')
                            for name in ('first', 'second', 'third')]
                self.assertEqual([s.width() for s in switches], [36] * 3)
                right_edges = [s.mapToItem(root, QPointF(s.width(), 0)).x() for s in switches]
                self.assertEqual(right_edges, [right_edges[0]] * 3)
        finally:
            if root is not None:
                delete(root)
            delete(component)
            delete(engine)

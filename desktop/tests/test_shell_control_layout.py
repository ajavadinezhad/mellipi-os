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

    def test_quick_wifi_last_result_scrolls_into_view_and_accepts_enter(self):
        from PyQt6.QtCore import QPointF, Qt, pyqtSignal
        from PyQt6.QtQuick import QQuickItem
        from native_app import Icons

        from PyQt6.QtCore import pyqtProperty, pyqtSlot

        class QuickOrbit(OrbitFixture):
            settingsChanged = pyqtSignal()
            controls = ['volume','brightness','connections','power']
            delay_snapshot = False

            @pyqtProperty('QVariantMap', notify=settingsChanged)
            def appearance(self):
                return dict(OrbitFixture.appearance.fget(self), quickControlOrder=self.controls)

            def bridge(self):
                from types import SimpleNamespace
                return SimpleNamespace(
                    preferences=SimpleNamespace(values={'quickControlOrder': self.controls}),
                    setQuickControlOrder=lambda order: self.setPreference('quickControlOrder', order))

            @pyqtSlot(str, int)
            def moveQuickControl(self, key, step):
                from native_app import Bridge
                Bridge.moveQuickControl(self.bridge(), key, step)

            @pyqtSlot(str, str, bool)
            def dropQuickControl(self, key, anchor, after):
                from native_app import Bridge
                Bridge.dropQuickControl(self.bridge(), key, anchor, after)

            @pyqtSlot(str, 'QVariant')
            def setPreference(self, key, value):
                if key == 'quickControlOrder':
                    self.controls = value.toVariant() if hasattr(value, 'toVariant') else value
                    if not self.delay_snapshot:
                        self.settingsChanged.emit()


        orbit = QuickOrbit()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit', orbit)
        engine.addImageProvider('icons', Icons())
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
        fixture = QQmlComponent(engine)
        fixture.setData(b'''
            import QtQuick 2.15
            QtObject {
                property QtObject network: QtObject {
                    property var values: ({audioAvailable: true, volume: 30, networkAvailable: true, networkState: "Connected",
                        wifiEnabled: true, wifiNetworks: Array.from({length: 12}, (_, i) =>
                            ({ssid: "Network " + (i+1), secure: true, signal: 80, active: false}))})
                    function refreshWifi() {}
                }
                property QtObject device: QtObject {
                    property var state: ({available: false, powered: false, percentageAvailable: false,
                        batteryPresent: false})
                    property var devices: []
                    property var brightnessWrites: []
                    function setBrightness(value) { brightnessWrites = brightnessWrites.concat([value]); }
                }
            }
        ''', QUrl.fromLocalFile(str(NATIVE / 'quick-networks-data-fixture.qml')))
        data = fixture.create()
        self.assertIsNotNone(data)
        for name, key in (('System', 'network'), ('Brightness', 'device'),
                          ('Power', 'device'), ('Bluetooth', 'device')):
            engine.rootContext().setContextProperty(name, data.property(key))
        component = QQmlComponent(engine)
        component.setData(b'''
            import QtQuick 2.15
            import QtQuick.Window 2.15
            import "."
            Window { id: fixtureWindow; width: 295; height: 275; visible: true
                QuickPanel { anchors.fill: parent; section: 1 }
            }
        ''', QUrl.fromLocalFile(str(NATIVE / 'quick-networks-fixture.qml')))
        window = component.create()
        try:
            self.assertIsNotNone(window, [e.toString() for e in component.errors()])
            window.requestActivate()
            QTest.qWait(80)
            def visual_items():
                pending = [window.contentItem()]
                items = {}
                while pending:
                    item = pending.pop()
                    items[item.objectName()] = item
                    pending.extend(item.childItems())
                return items

            rows = visual_items()
            last = rows['wifiNetwork_Network 12']
            first = rows['wifiNetwork_Network 1']
            scroller = rows['quickScrollBody'].property('contentItem')
            self.assertEqual(scroller.property('contentY'), 0)
            self.assertGreater(last.y(), first.y() + 300)
            last.forceActiveFocus()
            QTest.qWait(50)
            self.assertTrue(last.hasActiveFocus())
            self.assertGreater(scroller.property('contentY'), 0)
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(40)
            password = window.findChild(QQuickItem, 'wifiPassword')
            self.assertTrue(password.hasActiveFocus())
            self.assertEqual(scroller.property('contentY'), 0)
            QTest.keyClick(window, Qt.Key.Key_Escape)
            QTest.qWait(40)
            self.assertTrue(last.hasActiveFocus())
            self.assertFalse(visual_items()['wifiJoinForm'].isVisible())
            self.assertEqual(window.findChild(QQuickItem,'quickPanel').property('section'),1)
            back = window.findChild(QQuickItem, 'quickDetailBack')
            back.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(40)
            root = window.findChild(QQuickItem, 'quickPanel')
            self.assertEqual(root.property('section'), 0)
            self.assertTrue(visual_items()['quickSoundControls'].isVisible())
            connection = visual_items()['quickConnectionStatus']
            connection.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(40)
            self.assertEqual(root.property('section'), 1)
            self.assertTrue(back.hasActiveFocus())
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(40)
            self.assertTrue(connection.hasActiveFocus())
            self.assertFalse(visual_items()['quickGrip_volume'].isVisible())
            self.assertTrue(visual_items()['systemSettingsLink'].isVisible())
            devices = visual_items()['audioDevicesLink']
            devices.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(40)
            self.assertEqual(root.property('section'), 3)
            self.assertTrue(window.findChild(QQuickItem, 'quickOutputPicker').isVisible())
            self.assertFalse(visual_items()['systemSettingsLink'].isVisible())
            self.assertFalse(visual_items()['quickUpdates'].isVisible())
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(40)
            self.assertTrue(devices.hasActiveFocus())
            visual_items()['quickArrange'].forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(30)
            grip = visual_items()['quickGrip_connections']
            grip.forceActiveFocus()
            QTest.qWait(30)
            orbit.delay_snapshot = True
            QTest.keyClick(window, Qt.Key.Key_Up)
            QTest.keyClick(window, Qt.Key.Key_Up)
            self.assertEqual(orbit.controls, ['connections','volume','brightness','power'])
            orbit.delay_snapshot = False
            orbit.settingsChanged.emit()
            QTest.qWait(30)
            self.assertTrue(visual_items()['quickGrip_connections'].hasActiveFocus())
            orbit.setPreference('quickControlOrder', ['volume','brightness','connections','power'])
            QTest.qWait(30)
            grip = visual_items()['quickGrip_volume']
            destination = visual_items()['quickGrip_connections']
            start = grip.mapToScene(QPointF(grip.width()/2, grip.height()/2)).toPoint()
            end = destination.mapToScene(QPointF(destination.width()/2, 2)).toPoint()
            QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(window, start + (end-start)/2)
            QTest.mouseMove(window, end)
            QTest.qWait(40)
            self.assertTrue(visual_items()['quickDropMarker'].isVisible())
            QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
            QTest.qWait(30)
            self.assertEqual(orbit.controls, ['brightness','volume','connections','power'])
            self.assertFalse(visual_items()['quickDropMarker'].isVisible())
            orbit.setPreference('quickControlOrder', ['volume','brightness','connections','power'])
            QTest.qWait(30)
            device = data.property('device')
            device.setProperty('state',dict(available=True,powered=False,percentageAvailable=False,batteryPresent=False,backend='ddc',percent=30))
            slider = visual_items()['brightnessSlider']
            QTest.qWait(40)
            self.assertTrue(slider.isVisible())
            point=lambda x:slider.mapToScene(QPointF(slider.width()*x,slider.height()/2)).toPoint()
            QTest.mousePress(window,Qt.MouseButton.LeftButton,pos=point(.3))
            QTest.mouseMove(window,point(.55))
            QTest.qWait(160)
            self.assertEqual(device.property('brightnessWrites').toVariant(),[])
            QTest.mouseMove(window,point(.75))
            QTest.qWait(160)
            self.assertEqual(device.property('brightnessWrites').toVariant(),[])
            QTest.mouseRelease(window,Qt.MouseButton.LeftButton,pos=point(.75))
            writes=device.property('brightnessWrites').toVariant()
            self.assertEqual(len(writes),1)
            self.assertTrue(65<=writes[0]<=85,writes)
            self.assertEqual(warnings, [])
        finally:
            if window:
                window.close()
                delete(window)
            delete(component)
            delete(data)
            delete(fixture)
            delete(engine)

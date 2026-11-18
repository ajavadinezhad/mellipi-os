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
    saved = None

    outputs = Property('QVariantList', lambda _self: catalog([
        dict(name='HDMI-A-1', active=True, current_mode=dict(width=3240, height=1356, refresh=60000),
             modes=[dict(width=2560, height=1080, refresh=75000), dict(width=3280, height=1376, refresh=57000)]),
        dict(name='DP-1', model='Second monitor', active=True,
             current_mode=dict(width=1920, height=1080, refresh=60000),
             rect=dict(x=3240, y=0, width=1920, height=1080)),
    ]), notify=changed)
    state = Property('QVariantMap', lambda _self: dict(
        available=True, busy=False, pending=False, error='', arrangement=True), notify=changed)

    @Slot('QVariantList')
    def applyArrangement(self, rows):
        self.saved=rows

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
        topology = panel.property('topology').toVariant()
        self.assertEqual([(row['name'], row['x']) for row in topology],
                         [('HDMI-A-1', 0), ('DP-1', 3240)])
        self.assertEqual((topology[0]['w'], topology[0]['h']), (1085, 2592))
        # The visual draft stages both positions before handing off a single
        # transaction; switching the selected monitor must not drop the first.
        from PyQt6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(panel,'startArrangement')
        self.assertTrue(panel.property('arranging'))
        QMetaObject.invokeMethod(panel,'stagePosition',Q_ARG('QVariant','HDMI-A-1'),
                                 Q_ARG('QVariant',-3240),Q_ARG('QVariant',-80),Q_ARG('QVariant',False))
        QMetaObject.invokeMethod(panel,'loadOutput',Q_ARG('QVariant','DP-1'))
        QMetaObject.invokeMethod(panel,'stagePosition',Q_ARG('QVariant','DP-1'),
                                 Q_ARG('QVariant',7),Q_ARG('QVariant',50),Q_ARG('QVariant',True))
        self.assertTrue(panel.property('arrangementDirty'))
        QMetaObject.invokeMethod(panel,'finishArrangement',Q_ARG('QVariant',True))
        self.assertEqual(displays.saved,[dict(name='HDMI-A-1', x=-3240, y=-80),dict(name='DP-1', x=0, y=50)])
        self.assertEqual(warnings, [])

    def test_drag_and_keyboard_change_a_draft_before_any_backend_call(self):
        from PyQt6.QtCore import QMetaObject, QPointF, Qt
        from PyQt6.QtTest import QTest
        from test_settings_search_ui import OrbitFixture
        orbit, displays = OrbitFixture(), DisplayControls()
        engine = QQmlApplicationEngine()
        engine.addImageProvider('icons', Icons())
        engine.rootContext().setContextProperty('Orbit', orbit)
        engine.rootContext().setContextProperty('DisplayControls', displays)
        source = Path(__file__).resolve().parents[1] / 'native/display-drag-fixture.qml'
        component = QQmlComponent(engine)
        component.setData(b'''
            import QtQuick 2.15
            import QtQuick.Window 2.15
            import "."
            Window { width: 640; height: 840; visible: true
                DisplayPanel { anchors.fill: parent }
            }
        ''', QUrl.fromLocalFile(str(source)))
        window=component.create()
        try:
            self.assertIsNotNone(window,[row.toString() for row in component.errors()])
            panel=window.findChild(QObject,'displayPanel')
            QMetaObject.invokeMethod(panel,'startArrangement')
            window.requestActivate()
            QTest.qWait(60)
            def visual(node, name):
                if node.objectName()==name:return node
                for row in node.childItems():
                    if (found:=visual(row,name)) is not None:return found
            tile=visual(window.contentItem(),'displayLayoutTile_DP-1')
            self.assertIsNotNone(tile)
            tile.forceActiveFocus()
            QTest.keyClick(window,Qt.Key.Key_Down)
            self.assertEqual(panel.property('topology').toVariant()[1]['y'],32)
            begin=tile.mapToScene(QPointF(tile.width()*.5,tile.height()*.5)).toPoint()
            finish=begin+QPointF(-8,45).toPoint()
            QTest.mousePress(window,Qt.MouseButton.LeftButton,pos=begin)
            QTest.mouseMove(window,begin+QPointF(-6,22).toPoint(),30)
            QTest.mouseMove(window,finish,30)
            QTest.mouseRelease(window,Qt.MouseButton.LeftButton,pos=finish)
            QTest.qWait(50)
            self.assertGreater(panel.property('topology').toVariant()[1]['y'],32)
            self.assertIsNone(displays.saved)
        finally:
            if window:window.close();delete(window)
            delete(component);delete(engine)

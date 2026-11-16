"""Exercise retained taskbar slots with real Qt Quick bindings."""
from pathlib import Path
from unittest import TestCase, skipUnless

from qt_compat import QApplication, QQmlApplicationEngine, QT6_WAYLAND, QUrl


@skipUnless(QT6_WAYLAND, 'uses the production PyQt6 shell')
class TaskbarRetentionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtQml import QQmlComponent
        from native_app import Icons
        self.engine = QQmlApplicationEngine()
        self.engine.addImageProvider('icons', Icons())
        self.fixture_component = QQmlComponent(self.engine)
        self.fixture_component.setData(b'''import QtQuick 2.15
QtObject {
    property QtObject orbit: QtObject {
        property var appearance: ({panelPosition:"left",shellLayout:"fold",density:"extra",
                                    textScale:1.5,clock24:true,clockDate:true,reducedMotion:true})
        property bool compact:true
        property bool economy:true
        property color accentColor:"#b8d893"
        property string themeMode:"dark"
        property var desktops:[{id:0,active:true},{id:1,active:false}]
        property var outputWorkspaces:({})
        property var windows:[]
        property string panel:""
        property bool windowPlacementEnabled:true
        property var dockApps:[{id:"editor",name:"Editor",icon:"",windows:[]}]
        property bool nativePlacementSupported:false
        function queueItemTooltip(item,text,x,y) {}
        function hideTooltip() {}
        property var lastMove:[]
        function moveWindow(id,workspace) { lastMove=[id,workspace] }
    }
    property QtObject tray: QtObject { property var items: []; property int legacyCount:0 }
    property QtObject background: QtObject { property var items: [] }
    property QtObject system: QtObject {
        property var notifications: []; property var values: ({batteryPresent:false,muted:false})
    }
    property QtObject usage: QtObject { property string username:"test" }
    property QtObject power: QtObject { property var state: ({batteryPresent:false}) }
}
''', QUrl())
        self.fixture = self.fixture_component.create()
        self.assertIsNotNone(self.fixture, [e.toString() for e in self.fixture_component.errors()])
        for name in ('Orbit', 'Tray', 'Background', 'System', 'Usage', 'Power'):
            self.engine.rootContext().setContextProperty(name, self.fixture.property(name.lower()))
        self.component = QQmlComponent(self.engine)
        self.component.setData(b'''import QtQuick 2.15
import QtQuick.Window 2.15
import "."
Window {
    width:60; height:800; visible:true
    OrbitSpine { width:52; height:800; clockText:"23:59"; clockNow:new Date(2026,10,15) }
}
''', QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'native' / 'spine-probe.qml')))
        self.window = self.component.create()
        self.assertIsNotNone(self.window, [e.toString() for e in self.component.errors()])
        self.app.processEvents()

    def tearDown(self):
        from PyQt6.sip import delete
        if self.window:
            self.window.close()
            delete(self.window)
        delete(self.component)
        delete(self.engine)
        delete(self.fixture)
        delete(self.fixture_component)

    def item(self, predicate):
        pending = [self.window.contentItem()]
        while pending:
            item = pending.pop()
            if predicate(item):
                return item
            pending.extend(item.childItems())
        self.fail('Taskbar fixture item not found')

    def named(self, name):
        return self.item(lambda item: item.objectName() == name)

    def test_updates_retain_slot_objects_and_change_their_visible_state(self):
        orbit = self.fixture.property('orbit')
        task = self.named('spineTask_editor')
        workspace = self.named('spineWorkspace_1')
        self.assertFalse(task.property('running'))
        self.assertFalse(workspace.property('current'))
        orbit.setProperty('dockApps', [{'id':'editor','name':'Editor','icon':'',
                                        'windows':[{'id':'1','active':True}]}])
        orbit.setProperty('desktops', [{'id':0,'active':False},{'id':1,'active':True}])
        self.app.processEvents()
        self.assertIs(self.named('spineTask_editor'), task)
        self.assertIs(self.named('spineWorkspace_1'), workspace)
        self.assertTrue(task.property('running'))
        self.assertTrue(task.property('current'))
        self.assertTrue(workspace.property('current'))

    def test_extra_compact_clock_and_date_stay_legible_at_150_percent(self):
        for text in ('23:59', 'Nov 15'):
            label = self.item(lambda item: item.property('text') == text)
            self.assertFalse(label.property('truncated'), text)


    def test_small_viewport_preserves_click_targets_and_distinct_icon_sizes(self):
        from PyQt6.QtQuick import QQuickItem
        orbit=self.fixture.property('orbit')
        frame=self.named('orbitSpine').parentItem()
        for edge in ('left','right','top','bottom'):
            sizes=[]
            for scale in (75,100,125,150):
                orbit.setProperty('appearance',dict(panelPosition=edge,shellLayout='fold',density='extra',
                                  textScale=1.5,clock24=True,clockDate=True,reducedMotion=True,
                                  taskbarIconScale=scale))
                frame.setWidth(52 if edge in ('left','right') else 510)
                frame.setHeight(510 if edge in ('left','right') else 52)
                self.app.processEvents()
                target=self.named('spineControls')
                self.assertGreaterEqual(target.width(),24)
                self.assertGreaterEqual(target.height(),24)
                sizes.append(target.findChild(QQuickItem,'iconGlyph').width())
            self.assertEqual(sizes,[12,16,20,24],edge)
        orbit.setProperty('appearance',dict(panelPosition='left',shellLayout='fold',density='extra',
                          textScale=1.5,taskbarIconScale=150,reducedMotion=True))
        frame.setWidth(52)
        frame.setHeight(360)
        self.app.processEvents()
        self.assertTrue(self.named('spineUtilityOverflow').isVisible())


    def test_drag_single_window_to_workspace_without_switching(self):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtTest import QTest
        orbit=self.fixture.property('orbit')
        orbit.setProperty('dockApps',[dict(id='editor',name='Editor',icon='',
                                            windows=[dict(id='17',active=True,desktop=0)])])
        self.app.processEvents()
        task=self.named('spineTask_editor')
        workspace=self.named('spineWorkspace_1')
        def point(item):
            scene=item.mapToScene(QPointF(item.width()/2,item.height()/2))
            return QPoint(round(scene.x()),round(scene.y()))
        a,b=point(task),point(workspace)
        QTest.mousePress(self.window,Qt.MouseButton.LeftButton,pos=a)
        QTest.mouseMove(self.window,QPoint(a.x(),a.y()-16),25)
        QTest.mouseMove(self.window,b,25)
        QTest.mouseRelease(self.window,Qt.MouseButton.LeftButton,pos=b)
        self.app.processEvents()
        self.assertEqual(orbit.property('lastMove').toVariant(),['17',2])
        self.assertFalse(workspace.property('current'))

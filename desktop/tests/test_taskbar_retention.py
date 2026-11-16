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
        function syncSystemStripsMask(window) {}
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


    def test_added_apps_use_available_space_then_overflow_within_bar(self):
        orbit = self.fixture.property('orbit')
        frame = self.named('orbitSpine').parentItem()
        orbit.setProperty('appearance',dict(panelPosition='bottom',shellLayout='fold',density='extra',
                          textScale=1.5,taskbarIconScale=150,reducedMotion=True,taskbarLength='fit'))
        frame.setProperty('section','apps')
        frame.setWidth(850)
        frame.setHeight(52)
        self.app.processEvents()
        initial_width = frame.property('bodyLength')
        orbit.setProperty('dockApps',[dict(id=f'app{i}',name=f'App {i}',icon='',windows=[]) for i in range(14)])
        self.app.processEvents()
        self.assertGreater(frame.property('bodyLength'),initial_width)
        self.assertTrue(self.named('spineTask_app13').isVisible())
        self.assertFalse(self.named('spineAllWindows').isVisible())
        frame.setWidth(320)
        self.app.processEvents()
        overflow = self.named('spineAllWindows')
        self.assertTrue(overflow.isVisible())
        self.assertGreaterEqual(overflow.x(),0)
        self.assertLessEqual(overflow.x()+overflow.width(),overflow.parentItem().width())
        first, second = self.named('spineTask_app0'),self.named('spineTask_app1')
        self.assertGreaterEqual(second.x()-first.x()-first.width(),3)
        self.assertEqual(overflow.y(),first.y())

    def test_top_widget_and_controls_stay_in_their_own_lanes(self):
        from PyQt6.QtQml import QQmlComponent
        from PyQt6.sip import delete
        orbit = self.fixture.property('orbit')
        orbit.setProperty('appearance',dict(panelPosition='bottom',shellLayout='fold',density='extra',
                          textScale=1.5,clock24=True,clockDate=True,reducedMotion=True,taskbarIconScale=150))
        component = QQmlComponent(self.engine)
        component.setData(b'''import QtQuick 2.15
import "."
TopStrips {
    geometry: ({x:0,y:0,width:480,height:360})
    clockNow:new Date(2026,10,15,23,59);ready:true
    systemWidget: Component { Rectangle { objectName:"optionalWidget"; implicitWidth: 260 } }
}
''',QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'native' / 'strips-probe.qml')))
        window = component.create()
        self.assertIsNotNone(window,[e.toString() for e in component.errors()])
        try:
            def widgets():
                self.app.processEvents()
                stack=[window.contentItem()]
                result={}
                while stack:
                    item=stack.pop()
                    if item.isVisible() and item.objectName():
                        result[item.objectName()]=item
                    stack.extend(item.childItems())
                return result
            wide=widgets()
            self.assertIn('optionalWidget',wide)
            self.assertLess(wide['optionalWidget'].x()+wide['optionalWidget'].width(),window.width())
            window.setProperty('geometry',dict(x=0,y=0,width=180,height=360))
            narrow=widgets()
            self.assertNotIn('optionalWidget',narrow)
            self.assertIn('spineUtilityOverflow',narrow)
            spaces=window.property('workspaceRegion')
            utilities=window.property('utilityRegion')
            self.assertLess(spaces.right(),utilities.left())
            self.assertLess(utilities.right(),window.width())
            footer=narrow['spineFooter']
            self.assertLessEqual(footer.x()+footer.width(),utilities.width())
        finally:
            window.close()
            delete(window)
            delete(component)

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

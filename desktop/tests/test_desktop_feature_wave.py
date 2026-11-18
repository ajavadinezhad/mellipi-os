"""Private fixtures for naming spaces, searching favorites and desktop links."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from desktop_icons import DesktopIcons
from launcher_files import LauncherFiles
from native_app import Bridge
from preferences import Preferences
from qt_compat import QApplication


class DesktopFeatureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate, tick=lambda: None):
        deadline = monotonic()+4
        while monotonic()<deadline:
            self.app.processEvents()
            tick()
            if predicate():
                return
            sleep(.01)
        self.fail('Timed out waiting for the desktop fixture')

    def test_desktop_focus_follows_path_when_file_list_changes(self):
        from PyQt6.QtCore import QObject, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
        from native_app import Icons
        from qt_compat import QQmlApplicationEngine
        from test_settings_search_ui import NATIVE, OrbitFixture, QQmlComponent, QTest, delete

        class Desktop(QObject):
            changed = pyqtSignal()
            names=['Alpha','Beta']
            opened=[]
            items=pyqtProperty('QVariantList',lambda self:[
                dict(path='/fixture/'+name,name=name,kind='file',icon='text-plain') for name in self.names
            ],notify=changed)

            @pyqtSlot(str,int,int,result='QVariantMap')
            def layout(self,*_):
                return {row['path']:[i,0] for i,row in enumerate(self.items)}

            @pyqtSlot(str)
            def open(self,path):
                self.opened.append(path)

        engine=QQmlApplicationEngine()
        orbit,desktop=OrbitFixture(),Desktop()
        engine.rootContext().setContextProperty('Orbit',orbit)
        engine.rootContext().setContextProperty('FixtureDesktop',desktop)
        engine.addImageProvider('icons',Icons())
        component=QQmlComponent(engine)
        component.setData(b'\nimport QtQuick; import QtQuick.Window; import "."\nWindow {width:550;height:225;visible:true;DesktopIcons {anchors.fill:parent; controller: FixtureDesktop}}',
                          QUrl.fromLocalFile(str(NATIVE/'focus-files-fixture.qml')))
        window=component.create()
        try:
            self.assertIsNotNone(window,[e.toString() for e in component.errors()])
            window.requestActivate()
            QTest.qWait(30)
            grid=window.findChild(QObject,'desktopIconsGrid')
            grid.forceActiveFocus()
            QTest.keyClick(window,Qt.Key.Key_Right)
            QTest.keyClick(window,Qt.Key.Key_Right)
            self.assertEqual(grid.property('currentIndex'),1)
            desktop.names=['New','Alpha','Beta']
            desktop.changed.emit()
            QTest.qWait(30)
            QTest.keyClick(window,Qt.Key.Key_Return)
            self.assertEqual(desktop.opened,['/fixture/Beta'])
            desktop.names=['New','Alpha']
            desktop.changed.emit()
            QTest.qWait(30)
            QTest.keyClick(window,Qt.Key.Key_Return)
            self.assertEqual(desktop.opened,['/fixture/Beta'])
        finally:
            if window:
                window.close()
                delete(window)
            delete(component)
            delete(engine)

    def test_space_names_keep_numeric_identity_disambiguate_and_survive_reload(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'settings.json'
            signal = SimpleNamespace(emit=lambda:None)
            prefs=Preferences(path)
            bridge=SimpleNamespace(preferences=prefs, _desktops=[
                dict(id=0,name='Space 1'),dict(id=1,name='Space 2'),dict(id=2,name='Space 3'),
            ], windowsChanged=signal, systemActionsChanged=signal, notify=self.fail)
            self.assertTrue(Bridge.renameSpace(bridge,0,' Study '))
            self.assertTrue(Bridge.renameSpace(bridge,1,'study'))
            self.assertFalse(Bridge.renameSpace(bridge,3,'Unavailable'))
            bridge.preferences=Preferences(path)
            self.assertEqual([(row['id'],row['name']) for row in Bridge.namedDesktops(bridge)],
                             [(0,'Study (Space 1)'),(1,'study (Space 2)'),(2,'Space 3')])
            self.assertTrue(Bridge.renameSpace(bridge,1,''))
            self.assertEqual([row['name'] for row in Bridge.namedDesktops(bridge)],
                             ['Study','Space 2','Space 3'])

    def test_quick_order_is_a_strict_permutation_not_reset_with_appearance(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json'
            prefs=Preferences(path)
            order=['power','connections','brightness','volume']
            prefs.set('quickControlOrder',order)
            with self.assertRaises(ValueError):
                prefs.set('quickControlOrder',['power']*4)
            prefs.reset_appearance()
            self.assertEqual(Preferences(path).values['quickControlOrder'],order)

    def test_launcher_search_only_bookmark_and_latest_query_wins(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            folder=root/'favorite';outside=root/'outside'
            folder.mkdir();outside.mkdir()
            (folder/'sub').mkdir()
            (folder/'sub'/'report-new.txt').write_text('fixture')
            (folder/'old.txt').write_text('fixture')
            (outside/'report-outside.txt').write_text('outside')
            (folder/'link').symlink_to(outside, target_is_directory=True)
            settings=SimpleNamespace(sync=lambda:None,value=lambda *args:{str(folder):'Work'})
            opened=[]
            control=LauncherFiles(settings=settings,opener=lambda url:opened.append(url.toLocalFile()) or True)
            try:
                control.refresh()
                control.search(str(outside),'report')
                self.assertFalse(control._timer.isActive())
                control.search(str(folder),'old')
                control.search(str(folder),'report')
                self.wait_for(lambda:control.rows)
                self.assertEqual([row['name'] for row in control.rows],['report-new.txt'])
                control.open(str(outside/'report-outside.txt'))
                self.assertFalse(opened)
                control.open(control.rows[0]['id'])
                self.assertEqual(opened,[str(folder/'sub'/'report-new.txt')])
                control.search(str(folder),'old')
                control.cancel()
                self.assertEqual(control.rows,[])
                self.assertFalse(control._timer.isActive())
            finally:
                control.close()

    def test_dropping_two_links_from_same_site_keeps_original_urls(self):
        with TemporaryDirectory() as temp, patch.dict('os.environ',{'ORBIT_DATA':temp}):
            folder=Path(temp)/'Desktop';folder.mkdir()
            icons=DesktopIcons(enabled=True,directory=folder)
            try:
                urls=['https://example.invalid/first','https://example.invalid/second']
                icons.dropUrls(urls)
                def resolve():
                    if icons.transferState.get('conflict'):
                        icons.resolveTransferConflict('keep-both')
                self.wait_for(lambda:not icons.transferState.get('busy'),resolve)
                self.assertEqual(icons.transferState['completed'],2)
                self.assertEqual({line[4:] for item in folder.glob('*.desktop')
                                  for line in item.read_text().splitlines() if line.startswith('URL=')},set(urls))
            finally:
                icons.close()

    def test_launcher_file_mode_chooses_explicit_scope_and_enters_result(self):
        from PyQt6.QtCore import QMetaObject, QObject, QUrl, Qt, pyqtProperty
        from PyQt6.QtQml import QQmlComponent, QQmlApplicationEngine
        from PyQt6.QtTest import QTest
        from PyQt6.sip import delete
        from native_app import Icons
        from test_settings_search_ui import NATIVE, OrbitFixture

        with TemporaryDirectory() as temp:
            folder=Path(temp)
            expected=folder/'example.txt';expected.touch()
            settings=SimpleNamespace(sync=lambda:None,value=lambda *args:{temp:'Fixture'})
            opened=[]
            controller=LauncherFiles(settings=settings,opener=lambda url:opened.append(url.toLocalFile()) or True)

            class Orbit(OrbitFixture):
                launcherFiles=pyqtProperty(QObject,lambda _:controller,constant=True)
                launcherApps=pyqtProperty('QVariantList',lambda _:[],constant=True)
                windows=pyqtProperty('QVariantList',lambda _:[],constant=True)
                desktops=pyqtProperty('QVariantList',lambda _:[],constant=True)
                dockApps=pyqtProperty('QVariantList',lambda _:[],constant=True)
                windowFilter=pyqtProperty('QVariantList',lambda _:[],constant=True)

            orbit=Orbit()
            engine=QQmlApplicationEngine()
            engine.rootContext().setContextProperty('Orbit',orbit)
            engine.addImageProvider('icons',Icons())
            warnings=[]
            engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
            component=QQmlComponent(engine)
            component.setData(b'''
                import QtQuick 2.15
                import QtQuick.Window 2.15
                import "."
                Window {width:460;height:430;visible:true
                    UnifiedLauncher {anchors.fill: parent}
                }
            ''',QUrl.fromLocalFile(str(NATIVE/'file-mode-fixture.qml')))
            window=component.create()
            try:
                self.assertIsNotNone(window,[row.toString() for row in component.errors()])
                QTest.qWait(30)
                mode=window.findChild(QObject,'launcherFileMode')
                QMetaObject.invokeMethod(mode,'clicked')
                launcher=window.findChild(QObject,'unifiedLauncher')
                self.assertTrue(launcher.property('fileMode'))
                self.assertEqual(launcher.property('favoriteFolder'),str(expected.parent))
                search=window.findChild(QObject,'foldAppSearch')
                search.setProperty('text','example')
                window.requestActivate()
                search.forceActiveFocus()
                QTest.keyClick(window,Qt.Key.Key_Escape)
                self.assertFalse(launcher.property('fileMode'))
                self.assertEqual(search.property('text'),'example')
                QMetaObject.invokeMethod(mode,'clicked')
                self.assertTrue(launcher.property('fileMode'))
                self.wait_for(lambda:controller.rows)
                QTest.qWait(20)
                rows=launcher.property('results')
                self.assertEqual((rows.toVariant() if hasattr(rows,'toVariant') else rows)[0]['name'],'example.txt')
                window.requestActivate()
                search.forceActiveFocus()
                QTest.keyClick(window,Qt.Key.Key_Return)
                self.assertEqual(opened,[str(expected)])
                self.assertEqual(warnings,[])
            finally:
                if window:window.close();delete(window)
                delete(component);delete(engine);controller.close()

    def test_space_map_rename_can_be_entered_from_header_at_large_text(self):
        from PyQt6.QtCore import QMetaObject, QObject, QUrl, Qt, pyqtProperty, pyqtSignal, pyqtSlot
        from PyQt6.QtQml import QQmlComponent, QQmlApplicationEngine
        from PyQt6.QtTest import QTest
        from PyQt6.sip import delete
        from native_app import Icons
        from test_settings_search_ui import NATIVE, OrbitFixture

        class Orbit(OrbitFixture):
            windowsChanged=pyqtSignal()
            geometryChanged=pyqtSignal()
            @pyqtSlot(result='QVariantList')
            def spaceMapSnapshot(self):
                return [dict(id=0,name='Space 1', customName='', active=True,count=0,windows=[],tiles=[])]
            @pyqtSlot(int,str,result=bool)
            def renameSpace(self, ident, name):
                self.activated.append((ident,name))
                return True

        class Arrangements(QObject):
            checkpoints=pyqtProperty('QVariantList',lambda _:[],constant=True)
            busy=pyqtProperty(bool,lambda _:False,constant=True)
            undoAvailable=pyqtProperty(bool,lambda _:False,constant=True)
            undoLabel=pyqtProperty(str,lambda _:'',constant=True)

        orbit, arrangements=Orbit(), Arrangements()
        engine=QQmlApplicationEngine()
        engine.rootContext().setContextProperty('Orbit',orbit)
        engine.rootContext().setContextProperty('Arrangements',arrangements)
        engine.addImageProvider('icons',Icons())
        component=QQmlComponent(engine)
        component.setData(b'''
            import QtQuick 2.15
            import QtQuick.Window 2.15
            import "."
            Window {width:530;height:380;visible:true
                SpaceMap {anchors.fill: parent}
            }
        ''',QUrl.fromLocalFile(str(NATIVE/'rename-space-fixture.qml')))
        window=component.create()
        try:
            self.assertIsNotNone(window,[row.toString() for row in component.errors()])
            QTest.qWait(30)
            rename=window.findChild(QObject,'spaceMapRename')
            self.assertTrue(rename.property('visible'))
            QMetaObject.invokeMethod(rename,'clicked')
            name=window.findChild(QObject,'spaceMapNameField')
            name.setProperty('text','Study')
            window.requestActivate()
            name.forceActiveFocus()
            QTest.keyClick(window,Qt.Key.Key_Return)
            self.assertEqual(orbit.activated,[(0,'Study')])
            self.assertFalse(name.property('visible'))
        finally:
            if window:window.close();delete(window)
            delete(component);delete(engine)

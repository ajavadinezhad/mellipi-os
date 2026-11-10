"""Per-output static desktop/bar/dock surfaces; no extra processes or polling."""
from pathlib import Path
from panel_policy import panel_edge,panel_rect,taskbar_body_rect,panel_thickness
from qt_compat import QObject,QQuickWindow,QUrl,QRegion,QT5
if QT5:
    from PyQt5.QtQml import QQmlComponent,QQmlEngine
else:
    from PySide6.QtQml import QQmlComponent,QQmlEngine
ROOT=Path(__file__).resolve().parent

class SecondaryScreens(QObject):
    def __init__(self,engine,bridge):
        super().__init__(bridge);self.engine=engine;self.bridge=bridge;self.rows={};self.closed=False
        self.component=QQmlComponent(engine,QUrl.fromLocalFile(str(ROOT/'native/SecondaryScreen.qml')))
        bridge.displays.changed.connect(self.refresh);bridge.settingsChanged.connect(self.refresh);bridge.dockAppsChanged.connect(self.refresh)
        self.refresh()
    @property
    def state(self):
        return [dict(name=name,surfaces=len(row['windows']),geometry=dict(row['geometry'])) for name,row in self.rows.items()]
    def _remove(self,name):
        row=self.rows.pop(name);row['root'].setProperty('ready',False)
        for window in row['windows']:
            if window in self.bridge.shellWindows:self.bridge.shellWindows.remove(window)
            window.close()
        row['root'].deleteLater()
    def refresh(self):
        if self.closed or not self.bridge.isWayland:return
        wanted={s.name():s for s in self.bridge.app.screens() if s.name()!=self.bridge.selectedOutput}
        for name in list(self.rows):
            if name not in wanted or self.rows[name]['screen'] is not wanted[name] or self.rows[name]['layout']!=self.bridge.appearance['shellLayout'] or self.rows[name].get('position')!=panel_edge(self.bridge.appearance) or self.rows[name].get('floating')!=self.bridge.appearance.get('taskbarFloating',False) or self.rows[name].get('thickness')!=panel_thickness(self.bridge.appearance):self._remove(name)
        for name,screen in wanted.items():
            rect=screen.geometry();geometry=dict(x=rect.x(),y=rect.y(),width=rect.width(),height=rect.height())
            row=self.rows.get(name)
            if not row:
                root=self.component.create()
                if root is None:
                    self.bridge.notify('Could not create monitor panels: '+'; '.join(e.toString() for e in self.component.errors())[:220]);continue
                QQmlEngine.setObjectOwnership(root,QQmlEngine.CppOwnership)
                root.setProperty('screenName',name);root.setProperty('geometry',geometry)
                windows=list(root.findChildren(QQuickWindow))
                for window in windows:
                    QQmlEngine.setObjectOwnership(window,QQmlEngine.CppOwnership);window.setScreen(screen)
                row=dict(root=root,windows=windows,screen=screen,geometry=geometry,layout=self.bridge.appearance['shellLayout'],position=panel_edge(self.bridge.appearance),floating=self.bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(self.bridge.appearance));self.rows[name]=row
                self.bridge.shellWindows.extend(windows)
            row['geometry']=geometry;row['root'].setProperty('geometry',geometry)
            for window in row['windows']:
                if QT5:
                    from wayland_surfaces import configure
                    configure(window,window.objectName(),self.bridge.compact,self.bridge.appearance['dockAlign'],self.bridge.appearance['shellLayout']=='fold',panel_position=panel_edge(self.bridge.appearance),floating=self.bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(self.bridge.appearance))
                if window.objectName()=='secondaryTopbarSurface':
                    bar=panel_rect(geometry,self.bridge.appearance)
                    window.resize(bar['width'],bar['height'])
                    body=self.bridge.taskbarBodyRect(geometry)
                    window.setMask(QRegion(body['x']-bar['x'],body['y']-bar['y'],body['width'],body['height']))
                if window.objectName()=='secondaryDockSurface':
                    g=self.bridge.dockForWidth(geometry['width']);alignment=self.bridge.appearance['dockAlign']
                    x=0 if alignment=='left' else window.width()-g['bodyWidth'] if alignment=='right' else (window.width()-g['bodyWidth'])//2
                    window.setMask(QRegion(x,window.height()-g['bodyHeight'],g['bodyWidth'],g['bodyHeight']))
            row['root'].setProperty('ready',True)
        self.bridge.applyShellCursor()
    def close(self):
        if self.closed:return
        self.closed=True
        for name in list(self.rows):self._remove(name)

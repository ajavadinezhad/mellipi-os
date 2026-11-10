#!/usr/bin/env python3
"""Mellipi Qt Quick shell for the native desktop and isolated previews."""
import argparse, json, os, signal, sys, threading, uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from qt_compat import *
import core
import desktop
from preferences import Preferences, PRESETS
from panel_policy import SPINE_FOOTER_PANELS,CENTERED_PANELS,panel_edge,panel_rect,panel_body_origin,panel_mask_origin,panel_available_size,taskbar_body_rect,panel_thickness
from x11_events import DesktopEvents
from storage import LazyRustStore, PythonStore

from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT

def native_session():return bool(os.environ.get('ORBIT_NATIVE_CONTROL'))
def wayland_session():return native_session() or bool(os.environ.get('SWAYSOCK'))

class Icons(QQuickImageProvider):
    def __init__(self): super().__init__(QQuickImageProvider.Image if QT5 else QQuickImageProvider.ImageType.Image)
    def requestImage(self,ident,*sizes):
        requested=sizes[-1]
        icon=QIcon(ident) if ident.startswith('/') else QIcon.fromTheme(ident)
        if icon.isNull(): icon=QIcon.fromTheme('application-x-executable')
        side=max(16,min(64,requested.width() if requested.width()>0 else 40))
        image=icon.pixmap(QSize(side,side)).toImage()
        if image.isNull():
            image=QImage(64,64,QImage.Format.Format_ARGB32); image.fill(QColor('#486b61'))
        if QT5:return image,image.size()
        size=sizes[0];size.setWidth(image.width()); size.setHeight(image.height())
        return image

class Bridge(QObject):
    changed=Signal(); windowsChanged=Signal(); noticeChanged=Signal(); panelChanged=Signal(); aiChanged=Signal(); settingsChanged=Signal(); shortcutsChanged=Signal();geometryChanged=Signal();frameChanged=Signal();dockLayoutChanged=Signal();launcherChanged=Signal();interactionChanged=Signal()
    dockAppsChanged=Signal();systemActionsChanged=Signal()
    desktopSnapshot=Signal(object); shortcutUpdate=Signal(str); aiEvent=Signal(object)
    completed=Signal(object); hotkey=Signal(str); hardwareKey=Signal(str); actionRequested=Signal(str); quitRequested=Signal()
    def __init__(self,app,preferences=None,store=None):
        super().__init__(); self.app=app; self.preferences=preferences or Preferences(); self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit')
        self.store=store or PythonStore(); self.store.on_event=self.aiEvent.emit; self.aiEvent.connect(self.receiveAI); self._earlyAI=[]; self._undo=''; self._offset=0; self._total=0; self._search=[]; self._known={}
        self._settingsOpen=False;self._settingsDestination='system-settings';self._settingsSection=0;self._nativePaletteSupported=False
        self._dockApps=[];self._windowFilter=[];self._mru=[];self._switch=[];self._switchIndex=0;self._switchActive=False;self._tooltip={};self._context={}
        self.tooltipWindow=None;self.contextWindow=None
        self._pendingTooltip=None;self._tooltipAnchorSignals=[];self._tooltipLifecycleConnected=False
        self.tooltipTimer=QTimer(self);self.tooltipTimer.setSingleShot(True);self.tooltipTimer.setInterval(400);self.tooltipTimer.timeout.connect(self.publishTooltip)
        self._iconCache={}; self.desktopSnapshot.connect(self.applyWindowState); self.shortcutUpdate.connect(self.updateShortcuts)
        self._apps=desktop.applications();self._dockApps=desktop.dock_groups(self._apps,[],self.preferences.values['pins']); self._windows=[]; self._desktops=[]; self._objects=[]; self._workspaces=[]; self._links=[]
        from app_usage import AppUsage
        self.usage=AppUsage(self.preferences.path.with_name('app-usage.json'),self._apps)
        self._launcherApps=self.usage.rank(self._apps,self.preferences.values['launcherSort']);self._lastUsageWindow=None
        self._notice=''; self._panel=''; self._selected=[]; self._workspace='personal'; self._answer=''; self._answerReady=False; self._busy=False; self._job=''; self._polling=False
        self._surfacesReady=False
        self._hotkeys='Starting shortcuts…'; self.completed.connect(lambda fn:fn()); self.hotkey.connect(self.showPanel)
        self.actionRequested.connect(self.performAction)
        from displays import DisplaySettings
        self.displays=DisplaySettings(app,self.preferences.values['output'],self)
        self.displays.changed.connect(self.geometryChanged.emit)
        self._settingsPage='';self._panelRemapping=False;self._panelGeometry=None;self._panelMask={};self._contextSurfaceMode=None;self._panelPlacement=False;self._panelBottom=False
        from window_actions import WindowActions
        self.windowActions=WindowActions() if os.environ.get('SWAYSOCK') else None
        if native_session():
            from native_backend import NativeWindowActions
            self.windowActions=NativeWindowActions()
        self.xwaylandControls=None;self.nativeControlsEnabled=False;self.frameTrackingEnabled=False
        self._windowPool=None;self._windowPending=set()
        from app_catalog import AppCatalog
        self.appCatalog=AppCatalog(initial=self._apps,parent=self)
        self.appCatalog.catalogChanged.connect(self.applyAppCatalog);self.appCatalog.notice.connect(self.notify)
        from arrangements import Arrangements
        self.arrangements=Arrangements(self,self);self.arrangements.notice.connect(self.notify)
        self.settingsChanged.connect(self.systemActionsChanged.emit)
        from session_exit import SessionExit
        self.sessionExit=SessionExit(close_window=self.closeWindow,enabled=wayland_session() and not bool(os.environ.get('ORBIT_NESTED')))
        self.sessionExit.readyToExit.connect(self.finishQuit);self.sessionExit.focusRequested.connect(self.focusWindow)
        self.sessionExit.changed.connect(self.syncExitReviewFocus)
        self.settingsChanged.connect(self.applyNativePreferences)
        self.windowsChanged.connect(self.dockAppsChanged.emit);self.panelChanged.connect(self.dockAppsChanged.emit);self.panelChanged.connect(self.dockLayoutChanged.emit)
        self.panelWindow=None; self.desktopWindow=None;self.dockWindow=None;self._dockMask={}
        self.windowsChanged.connect(self.dockLayoutChanged.emit);self.geometryChanged.connect(self.dockLayoutChanged.emit);self.settingsChanged.connect(self.dockLayoutChanged.emit)
        if not getattr(self.store,'deferred',False):self.refresh()

    surfacesReady=Property(bool,lambda s:s._surfacesReady,notify=settingsChanged)
    isWayland=Property(bool,lambda s:wayland_session(),constant=True)
    nativeCompositor=Property(bool,lambda s:native_session(),constant=True)
    def currentScreen(self):return self.displays.screen() or self.app.primaryScreen()
    def screenMap(self):
        screen=self.currentScreen()
        if screen is None:return dict(x=0,y=0,width=800,height=600)
        g=screen.geometry();return dict(x=g.x(),y=g.y(),width=g.width(),height=g.height())
    screenGeometry=Property('QVariantMap',lambda s:s.screenMap(),notify=geometryChanged)
    outputs=Property('QVariantList',lambda s:s.displays.values,notify=geometryChanged)
    selectedOutput=Property(str,lambda s:s.displays.selectedName,notify=geometryChanged)

    appearance=Property('QVariantMap',lambda s:s.preferences.appearance(),notify=settingsChanged)
    @Property('QVariantList',constant=True)
    def themePresets(self):
        from theme_catalog import presets
        return presets()
    @Slot(str)
    def applyTheme(self,ident):
        try:self.preferences.apply_theme(ident)
        except (ValueError,OSError):return self.notify('Could not apply this theme')
        self.settingsChanged.emit();self.applyWindowTheme()
    aiEnabled=Property(bool,lambda s:os.environ.get('ORBIT_DEV_AI')=='1' and s.preferences.values['aiEnabled'],notify=settingsChanged)
    themeMode=Property(str,lambda s:s.preferences.values['mode'],notify=settingsChanged)
    workspaceMotion=Property(bool,lambda s:s.preferences.values['workspaceMotion'],notify=settingsChanged)
    nativePaletteSupported=Property(bool,lambda s:getattr(s,'_nativePaletteSupported',False),notify=interactionChanged)
    switchWindows=Property('QVariantList',lambda s:s._switch,notify=interactionChanged)
    switchIndex=Property(int,lambda s:s._switchIndex,notify=interactionChanged)
    switchActive=Property(bool,lambda s:s._switchActive,notify=interactionChanged)
    tooltip=Property('QVariantMap',lambda s:s._tooltip,notify=interactionChanged)
    context=Property('QVariantMap',lambda s:s._context,notify=interactionChanged)
    def dockLayout(self):
        from dock_layout import layout
        return layout(self.screenMap()['width'],self.compact,len(self.dockApps),fold=self.appearance.get('shellLayout')=='fold')
    dockGeometry=Property('QVariantMap',lambda s:s.dockLayout(),notify=dockLayoutChanged)
    @Slot(int,result='QVariantMap')
    def dockForWidth(self,width):
        from dock_layout import layout
        return layout(max(240,min(16384,width)),self.compact,len(self.dockApps),fold=self.appearance.get('shellLayout')=='fold')
    @Slot(str,str)
    def showPanelOn(self,name,output):
        def open_on_output():
            moving=output!=self.selectedOutput
            self.displays.setTransientName(output)
            if moving and self.panel==name:self.positionPanel(name);self.syncPanelGeometry(*self._panelGeometry[:2])
            else:self.showPanel(name)
        QTimer.singleShot(0,open_on_output)
    @Slot(str,str,int,int,str)
    def openContextOn(self,kind,ident,x,y,output):
        def open_on_output():
            self.displays.setTransientName(output);self.openContext(kind,ident,x,y)
        QTimer.singleShot(0,open_on_output)
    @Slot(str,bool)
    def setDesktopEditing(self,output,active):
        for window in getattr(self,'shellWindows',()):
            name=window.objectName()
            if name not in ('desktopSurface','secondaryDesktopSurface'):continue
            target=window.property('orbitOutputName') if name=='secondaryDesktopSurface' else self.selectedOutput
            if target!=output:continue
            window.setProperty('desktopEditing',active)
            if wayland_session():
                from wayland_surfaces import get,keyboard,sip
                keyboard(get(sip.unwrapinstance(window)),1 if active else 2)
            if active:QTimer.singleShot(0,window.requestActivate)
            break
    @Slot(int,str)
    def switchDesktopOn(self,ident,output):
        if not any(row['name']==output for row in self.outputs):return
        def switch():
            self.displays.setTransientName(output)
            if native_session():
                self.windowTask('__workspace__','switch',lambda:self.windowActions.client.switch_workspace(ident+1));return
            import sway_events
            current=next((d['id'] for d in self._desktops if d.get('output')==output and d.get('visible')),None)
            if current==ident:return
            self.dispatchWorkspaceAction(lambda:sway_events.command(f'focus output {json.dumps(output)}; workspace number {ident+1}'),1 if current is None or ident>current else -1)
        QTimer.singleShot(0,switch)
    @Slot(str)
    def performAction(self,action):
        from hardware_bindings import ACTIONS
        if action in ACTIONS:self.hardwareKey.emit(action);return
        if action=='next-layout':
            if hasattr(self,'inputControls'):self.inputControls.nextLayout()
            return
        if action in ('launcher','quick','screenshot'):self.showPanel(action);return
        if action=='terminal':
            try:desktop.launch_terminal()
            except (OSError,RuntimeError) as error:self.notify(str(error))
            return
        target=next((w for w in self._windows if w.get('active')),None)
        if not target or not self.windowActions:return
        ident=target['id']
        if action=='close-window':self.closeWindow(ident);return
        if action=='fullscreen-window' and native_session():
            self.windowTask(ident,'fullscreen',lambda:self.arrangements.engine.record_action('Fullscreen / restore',lambda:self.windowActions.client.request('fullscreen',id=int(ident),enabled=not target.get('fullscreen',False)),[int(ident)]),lambda _:self.arrangements.changed.emit());return
        if action.startswith('move-space-') and action.removeprefix('move-space-') in ('1','2','3','4'):self.moveWindow(ident,int(action.removeprefix('move-space-')));return
        if action=='maximize':self.maximizeWindow(ident);return
        if action not in ('snap-left','snap-right','restore'):return
        self.dismiss()
        def change():
            if action=='restore':self.windowActions.restore_size(int(ident))
            else:self.windowActions.snap(int(ident),action.split('-')[1])
            if self.xwaylandControls:self.xwaylandControls.restore_state(int(ident))
        self.windowTask(ident,action,lambda:self.arrangements.engine.record_action(action,change,[int(ident)]) if self.arrangements.engine else change(),lambda _:self.arrangements.changed.emit())
    def windowPalette(self):
        if not self.appearance.get('highContrast'):return self.appearance.get('themePalette',{})
        if self.themeMode=='light':
            return dict(background='#ffffff',surface='#ffffff',raised='#e6e6e6',hover='#d0d0d0',border='#000000',text='#000000',muted='#222222',faint='#333333')
        return dict(background='#000000',surface='#000000',raised='#161616',hover='#202020',border='#ffffff',text='#ffffff',muted='#eeeeee',faint='#dddddd')
    @Slot()
    def applyNativePreferences(self):
        if not native_session() or not self.windowActions:return
        settings=dict(economy=self.appearance['profile']=='economy',reduced_motion=self.appearance['reducedMotion'],enabled=self.appearance['workspaceMotion'])
        mode='light' if self.themeMode=='light' else 'black' if self.appearance['darkLevel']=='black' else 'dark'
        accent=self.accentColor
        palette=Bridge.windowPalette(self)
        outline=self.appearance.get('matchWindows',True)
        def configure():
            self.windowActions.client.request('motion',settings=settings)
            return self.windowActions.client.request('theme',mode=mode,accent=accent,palette=palette,outline=outline)
        def configured(result):
            supported=isinstance(result,dict) and 'palette_applied' in result
            if supported!=getattr(self,'_nativePaletteSupported',False):
                self._nativePaletteSupported=supported;self.interactionChanged.emit()
        def settled():
            latest=dict(economy=self.appearance['profile']=='economy',reduced_motion=self.appearance['reducedMotion'],enabled=self.appearance['workspaceMotion'])
            if latest!=settings or outline!=self.appearance.get('matchWindows',True) or palette!=Bridge.windowPalette(self) or accent!=self.accentColor or mode!=('light' if self.themeMode=='light' else 'black' if self.appearance['darkLevel']=='black' else 'dark'):self.applyNativePreferences()
        self.windowTask('__motion__','configure',configure,configured,settled=settled)
    @Slot(int,int,int,int)
    def updateDockMask(self,x,y,width,height):
        if self.dockWindow and width>0 and height>0:
            self.dockWindow.setMask(QRegion(x,y,width,height));self._dockMask=dict(x=x,y=y,width=width,height=height)
    @Slot(QObject,int,int,int,int)
    def maskSecondaryDock(self,window,x,y,width,height):
        if isinstance(window,QQuickWindow) and window.objectName()=='secondaryDockSurface' and width>0 and height>0:window.setMask(QRegion(x,y,width,height))
    def dockTasks(self):
        rows=list(self._dockApps)
        if self._settingsOpen:
            rows.append(dict(id='orbit-settings',name='Settings',icon='preferences-system',windows=[dict(id='orbit-settings',active=self._panel==self._settingsDestination,minimized=self._panel!=self._settingsDestination)],internal=True))
        return rows
    dockApps=Property('QVariantList',dockTasks,notify=dockAppsChanged)
    centeredPanels=Property('QVariantList',lambda s:list(CENTERED_PANELS),constant=True)
    quickSection=Property(int,lambda s:getattr(s,'_quickSection',0),notify=interactionChanged)
    settingsSection=Property(int,lambda s:s._settingsSection,notify=interactionChanged)
    settingsTarget=Property('QVariantMap',lambda s:getattr(s,'_settingsTarget',{}),notify=interactionChanged)
    @Slot(int)
    def rememberSettingsSection(self,section):
        if 0<=section<=17 and section!=self._settingsSection:self._settingsSection=section;self.interactionChanged.emit()
    @Slot(int)
    def openSettingsSection(self,section):
        self._settingsTarget={}
        if section==11:
            if self._panel=='notifications':self._panel=''
            self.showPanel('notifications');return
        if section==17:
            self._quickSection=2;self.interactionChanged.emit()
            if self._panel=='quick':self._panel=''
            self.showPanel('quick');return
        if section not in (0,1,2,3,4,5,6,7,8,9,10,11,12,15,16,17):return
        self.rememberSettingsSection(section)
        if self._panel=='system-settings':self._panel=''
        self.showPanel('system-settings')
    @Slot(int,int,str)
    def openSettingsTarget(self,section,tab,target):
        from action_targets import SETTING_TARGETS
        # Targets are an allowlist, not arbitrary QML names supplied over IPC.
        if (section,tab,target) not in SETTING_TARGETS.values():return
        self.openSettingsSection(section)
        self._settingsTarget=dict(section=section,tab=tab,target=target,serial=uuid.uuid4().hex)
        self.interactionChanged.emit()
    canSwitchUser=Property(bool,lambda s:bool(getattr(s,'systemServices',None) and s.systemServices.canSwitchUser),notify=settingsChanged)
    @Slot()
    def switchUser(self):
        if not self.canSwitchUser:return self.notify('Switch user is unavailable: the login screen and screen lock are required')
        self.dismiss();self.systemServices.switchUser()
    def actionCatalog(self):
        rows=[
            ('session','Power menu','Lock, log out, switch user, sleep, restart or shut down','system-shutdown','login sign in logout session power'),
            ('settings','System settings','All desktop and device settings','preferences-system','preferences configure controls'),
            ('sound','Sound settings','Choose speakers, microphone and audio profiles','audio-card','audio volume input output headset'),
            ('displays','Display settings','Resolution, scaling and monitor layout','video-display','screen monitor hdmi resolution scale'),
            ('network','Network settings','Wi-Fi and saved connections','network-wireless','wifi internet wireless ethernet vpn'),
            ('bluetooth','Bluetooth devices','Pair or connect a device','bluetooth','headphones wireless pair battery'),
            ('appearance','Appearance','Theme, colors and desktop layout','preferences-desktop-theme','dark light black theme accent wallpaper'),
            ('shortcuts','Keyboard shortcuts','Find and change keyboard shortcuts','preferences-desktop-keyboard-shortcuts','hotkeys keys bindings'),
            ('help','Getting around Mellipi','Learn where actions are and how to use the desktop','help-browser','help guide how login logout shortcuts'),
            ('lock','Lock screen','Lock this session; apps stay open','system-lock-screen','lock password privacy'),
            ('logout','Log out','Review apps before returning to the login screen','system-log-out','logout log out sign out login sign in'),
            ('suspend','Sleep','Open the Power menu to confirm sleep','system-suspend','suspend sleep standby'),
            ('reboot','Restart','Review apps before restarting the computer','system-reboot','restart reboot power'),
            ('shutdown','Shut down','Review apps before turning off the computer','system-shutdown','shutdown shut down power off turn off'),
        ]
        if self.canSwitchUser:rows.append(('switch-user','Switch user','Lock this session and open the login screen; apps stay open','system-switch-user','login sign in switch account user'))
        from action_targets import setting_actions
        result=[dict(id=key,name=name,description=description,icon=icon,searchText=' '.join((name,description,words)).lower(),destination='settings' if key=='settings' else 'action:'+key) for key,name,description,icon,words in rows]
        result.extend(setting_actions())
        result.extend([
            dict(id='screenshot',name='Take a screenshot',description='Choose display, area or window; copy and save the screenshot',icon='camera-photo',searchText='screenshot screen shot capture snip clipboard print screen',destination='panel:screenshot'),
            dict(id='do-not-disturb',name='Do not disturb',description='Open notification controls',icon='notifications-disabled',searchText='do not disturb dnd notifications quiet mute alerts',destination='panel:notifications'),
        ])
        return result
    systemActions=Property('QVariantList',actionCatalog,notify=systemActionsChanged)
    @Slot(str)
    def activateSystemAction(self,action):
        from action_targets import SETTING_TARGETS
        if action in SETTING_TARGETS:return self.openSettingsTarget(*SETTING_TARGETS[action])
        if action in ('screenshot','do-not-disturb'):
            panel='screenshot' if action=='screenshot' else 'notifications'
            if self._panel==panel:self._panel=''
            return self.showPanel(panel)
        sections={'session':17,'settings':getattr(self,'_settingsSection',10),'sound':8,'displays':2,'network':5,'bluetooth':9,'appearance':10,'shortcuts':3,'help':12,'suspend':17}
        if action in sections:self.openSettingsSection(sections[action])
        elif action=='logout':self.quit()
        elif action in ('reboot','shutdown'):self.requestPower(action)
        elif action=='switch-user':self.switchUser()
        elif action=='lock' and getattr(self,'systemServices',None):self.dismiss();self.systemServices.lock()
    @Slot()
    def closeSettingsTask(self):
        self._settingsOpen=False
        if self._panel in ('settings','system-settings'):self.dismiss()
        self.dockAppsChanged.emit();self.dockLayoutChanged.emit()
    @Slot()
    def closePanel(self):
        if self._panel in ('settings','system-settings'):self.closeSettingsTask()
        else:self.dismiss()

    windowFilter=Property('QVariantList',lambda s:s._windowFilter,notify=windowsChanged)
    apps=Property('QVariantList',lambda s:s._apps,notify=launcherChanged)
    launcherApps=Property('QVariantList',lambda s:s._launcherApps,notify=launcherChanged)
    windows=Property('QVariantList',lambda s:s._windows,notify=windowsChanged)
    desktops=Property('QVariantList',lambda s:s._desktops,notify=windowsChanged)
    objects=Property('QVariantList',lambda s:s._objects,notify=changed)
    searchResults=Property('QVariantList',lambda s:s._search,notify=changed)
    selectedObjects=Property('QVariantList',lambda s:[s._known[i] for i in s._selected if i in s._known],notify=changed)
    contextTotal=Property(int,lambda s:s._total,notify=changed)
    contextOffset=Property(int,lambda s:s._offset,notify=changed)
    links=Property('QVariantList',lambda s:s._links,notify=changed)
    workspaces=Property('QVariantList',lambda s:s._workspaces,notify=changed)
    selected=Property('QVariantList',lambda s:s._selected,notify=changed)
    workspace=Property(str,lambda s:s._workspace,notify=changed)
    notice=Property(str,lambda s:s._notice,notify=noticeChanged)
    footerPanels=Property('QVariantList',lambda s:list(SPINE_FOOTER_PANELS),constant=True)
    panel=Property(str,lambda s:s._panel,notify=panelChanged)
    answer=Property(str,lambda s:s._answer,notify=aiChanged)
    answerReady=Property(bool,lambda s:s._answerReady,notify=aiChanged)
    busy=Property(bool,lambda s:s._busy,notify=aiChanged)
    backendName=Property(str,lambda s:s.store.backend,constant=True)
    model=Property(str,lambda s:os.environ.get('ORBIT_AI_MODEL',''),constant=True)
    endpoint=Property(str,lambda s:os.environ.get('ORBIT_AI_URL','http://127.0.0.1:11434/v1'),constant=True)
    shortcutStatus=Property(str,lambda s:s._hotkeys,notify=shortcutsChanged)
    compact=Property(bool,lambda s:s.preferences.values['compact'],notify=settingsChanged)
    accentColor=Property(str,lambda s:s.preferences.values['accent'],notify=settingsChanged)
    economy=Property(bool,lambda s:s.preferences.values['profile']=='economy',notify=settingsChanged)
    accentPresets=Property('QVariantList',lambda s:PRESETS,constant=True)
    @Slot(str,'QVariant')
    def setPreference(self,key,value):
        remap=key=='shellLayout' and value!=self.preferences.values['shellLayout']
        if remap:self._surfacesReady=False;self.settingsChanged.emit()
        try: self.preferences.set(key,value)
        except (ValueError,OSError):
            if remap:self._surfacesReady=True;self.settingsChanged.emit()
            return self.notify('Could not save this setting')
        if key=='launcherSort':self.recordAppInteraction()
        if key=='output':self.displays.setRequestedName(value)
        if key=='pins':
            self._dockApps=desktop.dock_groups(self._apps,self._windows,self.preferences.values['pins']);self.windowsChanged.emit()
        self.settingsChanged.emit()
        if key in ('mode','accent','matchWindows','frameStyle','frameWidth','matchApps','darkLevel'):self.applyWindowTheme()
    @Slot()
    def resetAppearance(self):
        try:self.preferences.reset_appearance()
        except OSError:return self.notify('Could not reset appearance')
        self.settingsChanged.emit();self.applyWindowTheme()
    def bindResourceUsage(self,monitor):
        self.resourceUsage=monitor
        self.panelChanged.connect(lambda:monitor.setActive(self.panel=='usage' or (self.panel=='system-settings' and self._settingsPage=='usage')))
    def recordAppInteraction(self,ident=None,kind='launch'):
        mode=self.preferences.values['launcherSort']
        def work():
            if ident:self.usage.record(ident,kind)
            return self.usage.rank(self._apps,mode)
        def done(apps):
            if mode==self.preferences.values['launcherSort']:self._launcherApps=apps;self.launcherChanged.emit()
        self.asyncTask(work,done)
    @Slot()
    def clearLauncherHistory(self):
        mode=self.preferences.values['launcherSort']
        def work():return self.usage.reset(),self.usage.rank(self._apps,mode)
        def done(result):
            if not result[0]:return self.notify('Could not clear app usage history')
            if mode==self.preferences.values['launcherSort']:self._launcherApps=result[1];self.launcherChanged.emit()
            self.notify('Application history cleared')
        self.asyncTask(work,done)
    @Slot()
    def applyShellCursor(self):
        if not getattr(self,'shellWindows',None):return
        try:
            from shell_cursor import apply
            apply(self.shellWindows,self.themeMode,self.accentColor if self.appearance.get('cursorAccent',True) else None)
        except (OSError,ValueError):
            pass
    def applyWindowTheme(self):
        self.applyShellCursor()
        from application_theme import cursor_name
        os.environ['XCURSOR_THEME']=cursor_name(self.themeMode)
        os.environ.setdefault('XCURSOR_SIZE','24')
        if os.environ.get('SWAYSOCK'):
            from window_theme import apply_sway_theme
            mode,accent,width,style,level=self.themeMode,self.accentColor,self.appearance['frameWidth'],self.appearance['frameStyle'],self.appearance['darkLevel']
            self.asyncTask(lambda m=mode,a=accent,w=width,s=style,d=level:apply_sway_theme(m,a,w,s,d))
        elif not native_session() and os.environ.get('DISPLAY') and os.environ.get('QT_QPA_PLATFORM')!='offscreen':
            from window_theme import apply_xfwm_theme,restore_xfwm_theme
            mode,accent,enabled=self.themeMode,self.accentColor,self.appearance['matchWindows']
            self.asyncTask(lambda m=mode,a=accent,e=enabled:apply_xfwm_theme(ROOT,m,a) if e else restore_xfwm_theme(ROOT))
        if not os.environ.get('ORBIT_NESTED') and os.environ.get('QT_QPA_PLATFORM')!='offscreen':
            from application_theme import apply_application_theme,restore_application_theme,apply_cursor_theme
            mode,accent,enabled=self.themeMode,self.accentColor,self.appearance['matchApps']
            def sync_toolkits():
                result=apply_application_theme(ROOT,mode,accent) if enabled else restore_application_theme(ROOT)
                if not enabled:apply_cursor_theme(ROOT,mode)
                return result
            self.asyncTask(sync_toolkits)
    @Slot(str)
    def updateShortcuts(self,text): self._hotkeys=text; self.shortcutsChanged.emit()
    @Slot(str)
    def notify(self,text): self._notice=text; self.noticeChanged.emit()
    @Slot()
    def clearNotice(self): self._notice=''; self.noticeChanged.emit()
    def asyncTask(self,fn,done=None,on_error=None):
        try:future=self.pool.submit(fn)
        except RuntimeError:return # A queued device/catalog event may outlive teardown.
        def finished(f):
            try:
                result=f.result()
                try:self.completed.emit(lambda:done(result) if done else None)
                except RuntimeError:pass
            except Exception as e:
                message=str(e)
                self.completed.emit(lambda:on_error(message) if on_error else self.notify(message))
        future.add_done_callback(finished)
    def windowTask(self,ident,action,work,done=None,settled=None):
        """Serialize controls separately from sharing/theme work; bound repeated clicks."""
        def rejected():
            if settled:settled()
            return False
        if getattr(self,'_windowTasksClosed',False):return rejected()
        if action in ('focus','workspace-intent'):
            # Focus is an intent, unlike a close or maximize click. Keep one
            # queue slot and replace its target so B/A/B cannot end on A.
            prefix='_windowFocus' if action=='focus' else '_windowWorkspace'
            queued=prefix+'Queued';request_key=prefix+'Request'
            if not getattr(self,queued,False) and len(self._windowPending)>=64:return rejected()
            previous=getattr(self,request_key,None)
            request=(ident,work,done,settled)
            setattr(self,request_key,request)
            if getattr(self,queued,False):
                if previous and previous[3]:previous[3]()
                return True
            setattr(self,queued,True);running={}
            def focus_work():
                request=getattr(self,request_key);running['request']=request
                return request[1]()
            def focus_done(result):
                callback=running['request'][2]
                if callback:callback(result)
            def focus_settled():
                latest=getattr(self,request_key);setattr(self,request_key,None);setattr(self,queued,False)
                original=running.get('request')
                if original is None:
                    if latest and latest[3]:latest[3]()
                    return
                if original and original[3] and latest is original:original[3]()
                if latest is not running.get('request') and latest is not None:
                    Bridge.windowTask(self,latest[0],action,latest[1],latest[2],latest[3])
            return Bridge.windowTask(self,'__focus__' if action=='focus' else '__workspace__',action+'-queue',focus_work,focus_done,focus_settled)
        key=(ident,action)
        if action=='workarea' and key in self._windowPending:
            # A second geometry snapshot can arrive before the preceding
            # repair's completion is delivered. Retain one fresh recheck;
            # otherwise the changed snapshot is cached and never repaired.
            if not hasattr(self,'_windowWorkareaAgain'):self._windowWorkareaAgain={}
            self._windowWorkareaAgain[key]=(work,done)
            return
        if key in self._windowPending or len(self._windowPending)>=64:return rejected()
        if self._windowPool is None:self._windowPool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-windows')
        self._windowPending.add(key)
        self.frameChanged.emit()
        def finish(result=None,error=None):
            self._windowPending.discard(key)
            self.frameChanged.emit()
            try:
                if error is not None:self.notify(error)
                elif done:done(result)
            finally:
                if settled:settled()
                again=getattr(self,'_windowWorkareaAgain',{}).pop(key,None)
                if again:Bridge.windowTask(self,ident,action,again[0],again[1])
        def completed(future):
            try:result=future.result()
            except Exception as error:
                message=str(error);self.completed.emit(lambda:finish(error=message))
            else:self.completed.emit(lambda:finish(result))
        def run():
            result=work()
            if self.isWayland:
                try:
                    if native_session():self.desktopSnapshot.emit(self.windowActions.snapshot())
                    else:
                        from sway_events import window_snapshot
                        self.desktopSnapshot.emit(window_snapshot())
                except (OSError,ValueError,ConnectionError):pass
            return result
        try:self._windowPool.submit(run).add_done_callback(completed)
        except RuntimeError as error:finish(error=str(error));return False
        return True
    def closeWindowTasks(self):
        self._windowTasksClosed=True
        if self._windowPool:self._windowPool.shutdown(wait=True,cancel_futures=True)
    @Slot()
    def refresh(self):
        workspace,offset=self._workspace,self._offset
        def done(state):
            if workspace==self._workspace and offset==self._offset:self.applyContext(state)
        if self.store.backend=='python': done(self.store.state())
        else: self.asyncTask(lambda:self.store.state(workspace=workspace,offset=offset),done)
    def applyContext(self,state):
        total=state.get('total',len(state['objects']))
        if self._offset and self._offset>=total:
            self._offset=max(0,((total-1)//100)*100);self.refresh();return
        self._objects=state['objects']; self._workspaces=state['workspaces']; self._links=state['links']; self._total=state.get('total',len(self._objects)); self.trimContextCache(); self.changed.emit()
    def trimContextCache(self):
        self._known={**{i:o for i,o in self._known.items() if i in self._selected},**{o['id']:o for o in self._objects+self._search}}
    @Slot(int)
    def contextPage(self,direction):
        offset=max(0,self._offset+100*direction)
        if offset>=self._total and offset!=0:return
        self._offset=offset;self.refresh()
    @Slot(str)
    def searchContext(self,query):
        def done(state):self._search=state['objects'];self.trimContextCache();self.changed.emit()
        self.asyncTask(lambda:self.store.state(query=query),done)
    @Slot(str,int,int)
    def queueTooltip(self,text,x,y):
        # Connections are installed lazily: no extra timer or idle work. A panel,
        # output, or theme transition invalidates both pending and visible hints.
        if not getattr(self,'_tooltipLifecycleConnected',False):
            for name in ('panelChanged','geometryChanged','settingsChanged','dockLayoutChanged'):
                signal=getattr(self,name,None)
                if signal is not None:signal.connect(self.hideTooltip)
            self._tooltipLifecycleConnected=True
        self.hideTooltip()
        if not text:return
        self._pendingTooltip=dict(text=text[:120],x=x,y=y,panel=self._panel)
        self.tooltipTimer.start()
    def publishTooltip(self):
        from interactions import tooltip_position
        request=getattr(self,'_pendingTooltip',None)
        if not request:return
        if request['panel']!=self._panel:self.hideTooltip();return
        text,x,y=request['text'],request['x'],request['y']
        placement='auto';anchor_top=anchor_bottom=None
        anchor=request.get('anchor')
        if anchor is not None:
            try:
                if not anchor.isVisible() or not anchor.isEnabled():self.hideTooltip();return
                for property_name in ('hovered','containsMouse'):
                    if anchor.property(property_name) is False:self.hideTooltip();return
                px=anchor.width()*request['ratioX'] if request['ratioX'] is not None else request['localX']
                py=anchor.height()*request['ratioY'] if request['ratioY'] is not None else request['localY']
                point=self.itemScreenPoint(anchor,round(px),round(py))
                if not point:self.hideTooltip();return
                x,y=point['x'],point['y']
                top_point=self.itemScreenPoint(anchor,round(px),0);bottom_point=self.itemScreenPoint(anchor,round(px),round(anchor.height()))
                if not top_point or not bottom_point:self.hideTooltip();return
                anchor_top=top_point['y'];anchor_bottom=bottom_point['y']
                placement='above' if request['localY']<=0 else 'below'
            except (RuntimeError,TypeError):self.hideTooltip();return
        if self.currentScreen() is None:self.hideTooltip();return
        target=self.currentScreen()
        if hasattr(self,'app'):
            target=next((q for q in self.app.screens() if q.geometry().x()<=x<q.geometry().x()+q.geometry().width() and q.geometry().y()<=y<q.geometry().y()+q.geometry().height()),target)
        screen=target.geometry()
        width=min(300,max(80,len(text)*7+20));x,y=tooltip_position((screen.x(),screen.y(),screen.width(),screen.height()),x,y,width,34,placement=placement,anchor_top=anchor_top,anchor_bottom=anchor_bottom)
        if self.appearance.get('shellLayout')=='fold':
            edge=panel_edge(self.appearance)
            inset=panel_thickness(self.appearance)+12+(16 if self.appearance.get('taskbarFloating') else 0)
            left=screen.x()+(inset if edge=='left' else 8);right=screen.x()+screen.width()-(inset if edge=='right' else 8)
            top=screen.y()+(inset if edge=='top' else 8);bottom=screen.y()+screen.height()-(inset if edge=='bottom' else 8)
            x=max(left,min(x,right-width));y=max(top,min(y,bottom-34))
        # Mirror the same hint inside an open panel as well as in the small
        # native tooltip surface. The panel's own scene wins over its opaque
        # body; the native hint supplies any portion outside that scene/mask.
        inline=bool(self._panel and getattr(self,'panelWindow',None));local_x=local_y=0
        if inline:
            origin=self.panelTooltipOrigin();local_x=x-origin['x'];local_y=y-origin['y']
        self._tooltip=dict(text=text,x=x,y=y,width=width,inline=inline,localX=local_x,localY=local_y)
        if QT5 and wayland_session() and self.tooltipWindow:
            from wayland_surfaces import position_tooltip
            if self.tooltipWindow.screen() is not target:self.tooltipWindow.setScreen(target)
            position_tooltip(self.tooltipWindow,x-screen.x(),y-screen.y())
        self.interactionChanged.emit()
    @Slot()
    def hideTooltip(self):
        self.tooltipTimer.stop();had_tooltip=bool(self._tooltip)
        self._tooltip={};self._pendingTooltip=None
        connections=getattr(self,'_tooltipAnchorSignals',[]);self._tooltipAnchorSignals=[]
        for owner,signal,callback in connections:
            try:signal.disconnect(callback)
            except (RuntimeError,TypeError):pass
        if had_tooltip:self.interactionChanged.emit()
    @Slot(int)
    def cycleSwitch(self,step):
        from interactions import switch_order
        self.hideTooltip();self.closeContext()
        if not self._switchActive:
            self._switch=switch_order(self._windows,self._mru)
            if not self._switch:return
            self._switchIndex=0;self._switchActive=True;self.showPanel('switcher')
        self._switchIndex=(self._switchIndex+step)%len(self._switch);self.interactionChanged.emit()
    @Slot()
    def acceptSwitch(self):
        if not self._switchActive:return
        ident=self._switch[self._switchIndex]['id'];self._switchActive=False;self.interactionChanged.emit();self.dismiss();self.focusWindow(ident)
    @Slot()
    def cancelSwitch(self):self._switchActive=False;self.interactionChanged.emit();self.dismiss()
    @Slot(str,str,int,int)
    def openContext(self,kind,ident,x,y):
        self.hideTooltip();items=[]
        def add(label,action,value=''):items.append(dict(label=label,action=action,value=value))
        if kind in ('dock','app','window') and ident=='orbit-settings':
            add('Open Settings','settings-task');add('Close Settings','close-settings-task')
        elif kind=='desktop':
            add('New folder…','desktop-new-folder')
            add('Arrange icons','desktop-arrange',self.selectedOutput)
            add('Refresh desktop','desktop-refresh')
            add('Paste files','desktop-paste')
            add('Show desktop','show-desktop')
            for label,page in [('Applications','launcher'),('Appearance','settings'),('Settings','system-settings')]:add(label,'panel',page)
        elif kind in ('dock','app'):
            group=next((g for g in self._dockApps if g['id']==ident),None)
            if group and group['windows']:
                add('Switch to '+group['name'],'dock',ident)
                if len(group['windows'])>1:add('Choose window…','dock-all',ident)

            app=next((a for a in self._apps if a['id']==ident),None)
            if app:
                if not group or not group['windows']:add('Open '+app['name'],'launch',ident)
                add('Unpin from taskbar' if ident in self.preferences.values['pins'] else 'Pin to taskbar','pin',ident)
                add('Add to desktop','desktop-shortcut',ident)
            if group and len(group['windows'])==1:
                wid=group['windows'][0]['id'];add('Minimize','minimize-window',wid);add('Maximize / Restore size','maximize-window',wid);add('Close window','close-window',wid)
        elif kind=='desktop-file':
            add('Open','desktop-open',ident)
            if not ident.startswith('orbit-place:'):
                selected=getattr(self.desktopIcons,'selectedFiles',[])
                targets=selected if ident in selected else [ident]
                add('Open with…','desktop-open-with',ident)
                add('Show in folder','desktop-reveal',ident)
                add('Copy','desktop-copy-files',targets);add('Cut','desktop-cut-files',targets)
                add('Rename…','desktop-rename',ident)
                add('Move to Trash','desktop-trash-files',targets)
                add('Properties','desktop-properties',ident)
            add('Copy location' if ident.startswith('orbit-place:') else 'Copy path','desktop-copy',ident)
        elif kind=='fold-file' and getattr(self,'foldController',None):
            item=next((row for row in self.foldController.items if row['id']==ident),None)
            if item:
                add('Open folder' if item.get('isDir') else 'Open','fold-open',ident)
        elif kind=='window':
            target=next((w for w in self._windows if w['id']==ident),None)
            add('Restore window' if target and target.get('minimized') else 'Switch to window','focus',ident)
            add('Minimize','minimize-window',ident);add('Maximize / Restore size','maximize-window',ident);add('Close window','close-window',ident)
            if self.windowActions:
                add('Snap left','snap-window',[ident,'left']);add('Snap right','snap-window',[ident,'right'])
                for number in range(1,5):add('Move to workspace '+str(number),'move-window',[ident,number])
        if kind in ('desktop','window') and self.arrangements.undoLabel:add('Undo '+self.arrangements.undoLabel,'undo-arrangement')
        if kind=='object':
            add('Copy full content','copy',ident);add('Open','open',ident)
            if self.aiEnabled:add('Attach to AI','attach',ident)
            add('Remove from this collection','remove',ident)
        if not items:return
        self._context=dict(items=items,x=x,y=y)
        self.interactionChanged.emit()
    @Slot(QObject,int,int,result='QVariantMap')
    def itemScreenPoint(self,item,x,y):
        if not isinstance(item,QQuickItem):return {}
        if not self.isWayland:
            point=item.mapToGlobal(QPointF(x,y));return dict(x=round(point.x()),y=round(point.y()))
        # QQuickItem.window() can give PySide6 a reverse ownership edge from
        # a temporary QML item wrapper to its native window. Resolve against the
        # startup-owned surfaces instead, without exposing that borrowed getter.
        scene=item
        for _ in range(128):
            parent=scene.parentItem()
            if parent is None:break
            scene=parent
        else:return {}
        window=next((surface for surface in getattr(self,'shellWindows',()) if surface.contentItem()==scene),None)
        if window is None:return {}
        point=item.mapToScene(QPointF(x,y));screen=self.screenMap()
        output_name=window.property('orbitOutputName')
        if output_name:
            screen=next((r for r in self.outputs if r['name']==output_name),screen)
        left,top=screen['x'],screen['y'];name=window.objectName()
        if name=='overlaySurface':
            origin=Bridge.overlayOrigin(self,window.width(),window.height(),screen)
            left,top=origin['x'],origin['y']
        elif name in ('topbarSurface','secondaryTopbarSurface') and self.appearance.get('shellLayout')=='fold':
            rect=panel_rect(screen,self.appearance);left,top=rect['x'],rect['y']
        elif name in ('dockSurface','secondaryDockSurface'):
            alignment=self.appearance['dockAlign']
            left+=(12 if alignment=='left' else screen['width']-window.width()-12 if alignment=='right' else (screen['width']-window.width())/2)
            top+=screen['height']-window.height()-10
        return dict(x=round(left+point.x()),y=round(top+point.y()))
    @Slot(str,'QVariantMap',result='QVariantMap')
    def panelSurfaceRect(self,edge,screen):return panel_rect(screen,dict(self.appearance,panelPosition=edge))
    @Slot(str,int,int,'QVariantMap',str,result='QVariantMap')
    def panelPopupOrigin(self,panel,width,height,screen,edge):return panel_body_origin(panel,width,height,screen,edge,Bridge.taskbarBodyRect(self,screen))
    @Slot('QVariantMap',result='QVariantMap')
    def taskbarBodyRect(self,screen):
        return taskbar_body_rect(screen,self.appearance,len(getattr(self,'_dockApps',[]))+(1 if getattr(self,'_settingsOpen',False) else 0),getattr(self,'compact',True))
    @Slot(str,int,int,int,int,str,result='QVariantMap')
    def panelBodyMask(self,panel,bw,bh,width,height,edge):return panel_mask_origin(bw,bh,width,height,panel,edge)
    def itemSurfaceName(self,item):
        scene=item
        for _ in range(128):
            parent=scene.parentItem()
            if parent is None:break
            scene=parent
        else:return ''
        surface=next((window for window in getattr(self,'shellWindows',()) if window.contentItem()==scene),None)
        return surface.objectName() if surface else ''
    def overlayOrigin(self,width,height,screen=None):
        screen=screen or self.screenMap()
        if getattr(self,'_panel','') in CENTERED_PANELS:return dict(x=screen['x']+(screen['width']-width)/2,y=screen['y']+(screen['height']-height)/2)
        spine=self.appearance.get('shellLayout')=='fold';right=getattr(self,'_panelPlacement',False)
        if spine:return panel_body_origin(getattr(self,'_panel',''),width,height,screen,panel_edge(self.appearance),Bridge.taskbarBodyRect(self,screen))
        return dict(x=screen['x']+(76 if spine else screen['width']-width-12 if right else (screen['width']-width)/2),y=screen['y']+((screen['height']-height-16 if getattr(self,'_panelBottom',False) else 16) if spine else 42 if right else (screen['height']-height)/2))
    def panelTooltipOrigin(self):
        window=self.panelWindow;origin=Bridge.overlayOrigin(self,window.width(),window.height())
        return dict(origin,width=window.width(),height=window.height())
    @Slot(QObject,str,int,int)
    def queueItemTooltip(self,item,text,x,y):
        if not isinstance(item,QQuickItem):self.hideTooltip();return
        try:
            if not item.isVisible() or not item.isEnabled():self.hideTooltip();return
            point=self.itemScreenPoint(item,x,y)
            if not point:self.hideTooltip();return
            self.queueTooltip(text,point['x'],point['y'])
            request=getattr(self,'_pendingTooltip',None)
            if not request:return
            # A single retained wrapper avoids weakref expiry for live PyQt QML
            # objects. Loader destruction still invalidates it and cancels below.
            request.update(anchor=item,localX=x,localY=y,ratioX=x/item.width() if item.width()>0 else None,ratioY=y/item.height() if item.height()>0 else None)
            def changed(*_):
                if getattr(self,'_pendingTooltip',None) is not request:return
                try:
                    if not item.isVisible() or not item.isEnabled():self.hideTooltip();return
                    for property_name in ('hovered','containsMouse'):
                        if item.property(property_name) is False:self.hideTooltip();return
                except (RuntimeError,TypeError):self.hideTooltip();return
                if self._tooltip:self.publishTooltip()
            connections=[];self._tooltipAnchorSignals=connections
            ancestor=item
            for depth in range(32):
                def destroyed(*_,owner=ancestor):
                    if getattr(self,'_pendingTooltip',None) is request:
                        # Qt has already removed derived signals while emitting
                        # QObject::destroyed. Let that object's destructor remove
                        # its connections; explicitly detach only live ancestors.
                        self._tooltipAnchorSignals=[entry for entry in self._tooltipAnchorSignals if entry[0] is not owner]
                        self.hideTooltip()
                ancestor.destroyed.connect(destroyed);connections.append((ancestor,ancestor.destroyed,destroyed))
                names=('xChanged','yChanged','visibleChanged','enabledChanged')+ (('widthChanged','heightChanged','hoveredChanged','containsMouseChanged') if depth==0 else ())
                for name in names:
                    signal=getattr(ancestor,name,None)
                    if signal is not None:signal.connect(changed);connections.append((ancestor,signal,changed))
                ancestor=ancestor.parentItem()
                if ancestor is None:break
            self._tooltipAnchorSignals=connections
        except (RuntimeError,TypeError):self.hideTooltip()
    @Slot(QObject,str,str,int,int)
    def openPanelContext(self,item,kind,ident,x,y):
        point=self.itemScreenPoint(item,x,y)
        if point:self.openContext(kind,ident,point['x'],point['y'])
    @Slot(str)
    def togglePin(self,ident):
        if not any(a['id']==ident for a in self._apps):return
        pins=list(self.appearance['pins'])
        if ident in pins:pins.remove(ident)
        else:pins.append(ident)
        self.setPreference('pins',pins)
    @Slot(str,int,int)
    def openDockContext(self,ident,x,y):
        self.openContext('dock',ident,x,y)
        if self._context:self._context={**self._context,'placement':'above'};self.interactionChanged.emit()
    @Slot()
    def closeContext(self):
        had_context=bool(self._context);self._context={};self.interactionChanged.emit()
        if had_context and self._panel:self.positionPanel(self._panel)
    @Slot(int)
    def contextAction(self,index):
        items=self._context.get('items',[])
        if not 0<=index<len(items):return
        item=items[index]
        if not item.get('enabled',True):return
        self.closeContext();action,value=item['action'],item['value']
        if action=='tray-menu':self.trayHost.clickMenu(value[0],value[1])
        elif action=='panel':self.showPanel(value)
        elif action=='settings-task':self.showPanel(self._settingsDestination)
        elif action=='close-settings-task':self.closeSettingsTask()
        elif action=='dock':self.activateDock(value,False)
        elif action=='dock-all':self.activateDock(value,True)
        elif action=='launch':self.launch(value)
        elif action=='focus':self.focusWindow(value)
        elif action=='copy':self.copy(value)
        elif action=='open':self.openObject(value)
        elif action=='attach':self.attach(value)
        elif action=='remove':self.remove(value)
        elif action=='show-desktop':self.showDesktop()
        elif action=='desktop-shortcut':self.desktopIcons.addShortcut(value)
        elif action=='desktop-open':self.desktopIcons.open(value)
        elif action=='desktop-reveal':self.desktopIcons.reveal(value)
        elif action=='desktop-paste':self.desktopIcons.pasteFiles()
        elif action=='desktop-copy-files':self.desktopIcons.copyFiles(value)
        elif action=='desktop-cut-files':self.desktopIcons.cutFiles(value)
        elif action=='desktop-trash-files':self.desktopIcons.trashFiles(value)
        elif action=='desktop-open-with':self.desktopIcons.openWith(value)
        elif action=='desktop-properties':self.desktopIcons.properties(value)
        elif action=='desktop-copy':self.desktopIcons.copyPath(value)
        elif action=='desktop-rename':self.desktopIcons.requestRename(value)
        elif action=='desktop-trash':self.desktopIcons.moveToTrash(value)
        elif action=='desktop-new-folder':self.desktopIcons.requestNewFolder()
        elif action=='desktop-arrange':self.desktopIcons.arrange(value)
        elif action=='desktop-refresh':self.desktopIcons.refresh()
        elif action=='fold-open':self.dismiss();self.foldController.openItem(value)
        elif action=='fold-carry':self.foldController.carry(value)
        elif action=='pin':self.togglePin(value)
        elif action=='minimize-window':self.minimizeWindow(value)
        elif action=='maximize-window':self.maximizeWindow(value)
        elif action=='close-window':self.closeWindow(value)
        elif action=='undo-arrangement':self.arrangements.undo()
        elif action=='snap-window':self.arrangeWindow(value[0],value[1])
        elif action=='move-window':self.moveWindow(value[0],value[1])
    @Slot(str,str)
    def arrangeWindow(self,ident,side):
        if not self.windowActions or side not in ('left','right'):return
        self.windowTask(ident,'snap',lambda:self.arrangements.engine.record_action('Snap '+side,lambda:self.windowActions.snap(int(ident),side),[int(ident)]),lambda _:self.arrangements.changed.emit())
    @Slot(str,int)
    def moveWindow(self,ident,number):
        if not self.windowActions or not 1<=number<=99:return
        self.windowTask(ident,'move',lambda:self.arrangements.engine.record_action('Move to workspace '+str(number),lambda:self.windowActions.command(f'[con_id={int(ident)}] move container to workspace number {number}'),[int(ident)]),lambda _:self.arrangements.changed.emit())
    @Slot(str)
    def minimizeWindow(self,ident):
        if ident=="orbit-settings":self.dismiss();return
        if not any(w['id']==ident for w in self._windows):return
        self.dismiss()
        if self.windowActions:self.windowTask(ident,'minimize',lambda:self.windowActions.minimize(int(ident)))
        else:self.windowTask(ident,'minimize',lambda:desktop.command(['xdotool','windowminimize',ident]))
    @Slot(str)
    def maximizeWindow(self,ident):
        target=next((w for w in self._windows if w['id']==ident),None)
        if not target:return
        self.dismiss()
        if self.windowActions:
            if target.get('xid') and self.xwaylandControls:
                def action():
                    # Xlib connects lazily. Resolve that startup race here on
                    # the worker, preserving GTK's pre-resize maximize state.
                    if self.xwaylandControls.ensure_ready():return self.xwaylandControls.maximize(int(ident))
                    return self.windowActions.maximize(int(ident))
            else:action=lambda:self.windowActions.maximize(int(ident))
            self.windowTask(ident,'maximize',lambda:self.arrangements.engine.record_action('Maximize / restore',action,[int(ident)]),lambda _:(self.frameChanged.emit(),self.arrangements.changed.emit()))
        else:self.windowTask(ident,'maximize',lambda:desktop.command(['wmctrl','-ir',ident,'-b','toggle,maximized_vert,maximized_horz']))
    @Slot(str)
    def closeWindow(self,ident):
        if ident=="orbit-settings":self.closeSettingsTask();return
        if not any(w['id']==ident for w in self._windows):return False
        generation=self.sessionExit._generation
        def close_action(work):
            def run():
                try:return work()
                except Exception as error:
                    self.completed.emit(lambda message=str(error):self.sessionExit.closeFailed(ident,message,generation))
                    raise
            return self.windowTask(ident,'close',run)
        if native_session():return close_action(lambda:self.windowActions.close(int(ident)))
        elif os.environ.get('SWAYSOCK'):
            import sway_events;return close_action(lambda:sway_events.command(f'[con_id={int(ident)}] kill'))
        else:return close_action(lambda:desktop.command(['wmctrl','-ic',ident]))
    @Slot()
    def utilityFocusLost(self):
        # Closing a client can activate its save dialog. Preserve confirmed
        # exit consent while that application temporarily owns keyboard focus.
        if self._panel=='session-exit' and self.sessionExit.state['armed']:return
        if not self._panelRemapping and not self._context and self._panel and self._panel!='switcher':self.dismiss()
    def syncExitReviewFocus(self):
        if QT5 and self.isWayland and getattr(self,'panelWindow',None) and self._panel=='session-exit':
            from wayland_surfaces import get,keyboard,sip
            keyboard(get(sip.unwrapinstance(self.panelWindow)),2 if self.sessionExit.state['armed'] else 1)
    @Slot(int,int)
    def syncPanelGeometry(self,width,height):
        if not self.panelWindow or not self._panel or self._panelRemapping:return
        screen=self.screenMap();spine=self.appearance.get('shellLayout')=='fold'
        available=panel_available_size(screen,self.appearance) if spine else dict(width=screen['width']-24,height=screen['height']-100)
        width=max(1,min(width,available['width'],760));height=max(1,min(height,available['height'],620))
        right=self._panel in SPINE_FOOTER_PANELS
        self._panelRemapping=True
        try:
            window=self.panelWindow
            if QT5 and wayland_session():
                # One stable layer buffer: Qt5 may ignore mapped resizing and
                # recreating its role can commit before the first configure.
                # Only the inner body and matching input region change size.
                centered=self._panel in CENTERED_PANELS
                if spine:
                    mask=panel_mask_origin(window.width(),window.height(),width,height,self._panel,panel_edge(self.appearance));x,y=mask['x'],mask['y']
                else:
                    x=(window.width()-width+1)//2 if centered else window.width()-width if right else (window.width()-width+1)//2
                    y=(window.height()-height+1)//2 if centered else 0 if right else (window.height()-height+1)//2
            else:
                window.resize(width,height);x=y=0
            window.setMask(QRegion(x,y,width,height));self._panelGeometry=(width,height,right)
            self._panelMask=dict(x=x,y=y,width=width,height=height)
            if getattr(self,'contextWindow',None):self.syncContextSurface()
        finally:self._panelRemapping=False
    @Slot()
    def settlePanelFocus(self):
        if QT5 and self.isWayland and self.panelWindow and not self._panel:
            from wayland_surfaces import get,keyboard,sip
            keyboard(get(sip.unwrapinstance(self.panelWindow)),2)
    @Slot()
    def syncContextSurface(self):
        if not self.contextWindow or not self.isWayland or not QT5:return
        screen=self.screenMap();menu=bool(self._context);spine=self.appearance.get('shellLayout')=='fold';bar=0 if spine else 30 if self.compact else 38;bottom=0 if spine else 62 if self.compact else 76;left=64 if spine else 0
        edge=panel_edge(self.appearance);right=0
        if spine:
            reserve=panel_thickness(self.appearance)+(16 if self.appearance.get('taskbarFloating') else 0)
            left=reserve if edge=='left' else 0;right=reserve if edge=='right' else 0;bar=reserve if edge=='top' else 0;bottom=reserve if edge=='bottom' else 0
        key=(menu,screen['width'],screen['height'],bar,bottom,left,right,bool(self._panel))
        if self._contextSurfaceMode==key:return
        from wayland_surfaces import get,keyboard,layer,sip
        native=get(sip.unwrapinstance(self.contextWindow));layer(native,3 if menu else 2);keyboard(native,1 if menu else 0)
        self.contextWindow.setMask(QRegion(0,0,screen['width'],screen['height']) if menu else QRegion(left,bar,max(1,screen['width']-left-right),max(1,screen['height']-bar-bottom)))
        self._contextSurfaceMode=key
    @Slot(str)
    def positionPanel(self,name):
        if QT5 and wayland_session() and self.panelWindow:
            from wayland_surfaces import position_overlay
            self._panelBottom=self.appearance.get('shellLayout')=='fold' and name in SPINE_FOOTER_PANELS
            position_overlay(self.panelWindow,name,self.appearance.get('shellLayout')=='fold',panel_position=panel_edge(self.appearance),screen_geometry=self.screenMap(),bar_geometry=self.taskbarBodyRect(self.screenMap()))
            self._panelPlacement=self.appearance.get('shellLayout')!='fold' and name in SPINE_FOOTER_PANELS
            self.syncContextSurface()
    @Slot(str)
    def settingsPageOpened(self,name):
        if self._panel!='system-settings' and not getattr(getattr(self,'settingsHost',None),'active',False):return
        previous=self._settingsPage;self._settingsPage=name
        if previous=='bluetooth' and name!='bluetooth' and hasattr(self,'bluetoothControls'):
            self.bluetoothControls.stopDiscovery();self.bluetoothControls.cancelPairing()
        if hasattr(self,'resourceUsage'):self.resourceUsage.setActive(name=='usage')
        if hasattr(self,'trayHost'):self.trayHost.showLegacy(name=='tray')
        if name=='music' and hasattr(self,'systemServices'):self.systemServices.refreshAudio()
        elif name=='battery' and hasattr(self,'powerControls'):self.powerControls.refresh()
        elif name=='brightness' and hasattr(self,'brightnessControls'):self.brightnessControls.refresh()
        elif name=='tray' and getattr(self,'legacyProxy',None):self.legacyProxy.start()

    @Slot(str)
    def showPanel(self,name):
        if name in ('settings','system-settings') and getattr(self,'settingsHost',None):
            section=10 if name=='settings' else self._settingsSection
            self._settingsOpen=False;self.dismiss();self.settingsHost.show(section);return
        if name!='session-exit' and self.sessionExit.state['active']:self.sessionExit.cancel()
        if name=='shelf':return self.notify('Sharing has been removed')
        hardwareSections={'bluetooth':9,'battery':7}
        if name in hardwareSections:
            self._settingsSection=hardwareSections[name];self.interactionChanged.emit();name='system-settings'
            # A deep link selects a page even if settings is already visible.
            if self._panel==name:self._panel=''
        if name=='fold' or (name=='overview' and self.appearance.get('shellLayout')=='fold'):name='launcher'
        if name=='launcher' and self._windowFilter:self._windowFilter=[];self.windowsChanged.emit()
        if name=='ai' and not self.aiEnabled:name='launcher'
        if name in ('ai','capture'):self.refresh()
        if name=='launcher':self.refreshAppCatalog()
        if name in ('settings','system-settings'):self._settingsOpen=True;self._settingsDestination=name
        fold=getattr(self,'foldController',None)
        if fold and self._panel!=name and self.appearance.get('shellLayout')=='fold' and name in ('launcher','overview'):
            fold.setView('apps')
        if name=='overview':self._windowFilter=[];self.windowsChanged.emit()
        self._panel='' if self._panel==name and name!='session-exit' else name
        if self._panel!='system-settings':self._settingsPage=''
        if fold:fold.setActive(bool(self._panel in ('launcher','overview') and self.appearance.get('shellLayout')=='fold' and fold.state['view']=='work'))
        if self._panel:self.positionPanel(self._panel)
        else:self.settlePanelFocus()
        self.panelChanged.emit()
        if self._panel: self.refreshWindows()
        if self._panel and self.panelWindow:
            if not os.environ.get('SWAYSOCK'):self.panelWindow.raise_();self.panelWindow.requestActivate()
    @Slot()
    def dismiss(self):
        self._quickSection=0
        self.sessionExit.cancel()
        self._panel='';self._switchActive=False
        if getattr(self,'foldController',None):self.foldController.setActive(False)
        self.settlePanelFocus();self.panelChanged.emit();self.interactionChanged.emit()
    @Slot(str)
    def setWorkspace(self,ident):
        if ident in [w['id'] for w in self._workspaces]: self._workspace=ident; self._offset=0; self.refresh()
    @Slot(str)
    def attach(self,ident):
        if ident not in self._known:return
        if ident in self._selected: self._selected.remove(ident)
        elif len(self._selected)<20: self._selected.append(ident)
        else: return self.notify('Attach up to 20 items per request')
        self.changed.emit()
    @Slot(str,str)
    def capture(self,title,body):
        data=dict(title=title,body=body,kind='note',workspace=self._workspace)
        def done(_):
            self.refresh(); self.notify('Saved locally'); self._panel='launcher'; self.panelChanged.emit()
        if self.store.backend=='python':
            try: done(self.store.create(data))
            except ValueError as e:self.notify(str(e))
        else:self.asyncTask(lambda:self.store.create(data),done)
    @Slot()
    def captureClipboard(self):
        cb=self.app.clipboard(); mime=cb.mimeData()
        if mime.hasUrls(): return self.importFiles([u.toString() for u in mime.urls()])
        text=cb.text().strip()
        if not text: return self.notify('Clipboard has no text or local files')
        self.capture(text.splitlines()[0][:80],text)
    @Slot('QVariantList')
    def importFiles(self,uris):
        if len(uris)>20: return self.notify('Drop up to 20 files at a time')
        workspace=self._workspace
        def work():
            failures=[];added=0
            for uri in uris:
                try:
                    path=desktop.local_file(str(uri));content=path.as_uri()
                    if path.suffix.lower() in ('.txt','.md','.csv','.json','.py','.rs','.qml','.log','.html','.css','.js') and path.stat().st_size<=90000:
                        try: content=path.read_text(encoding='utf-8')
                        except UnicodeError: pass
                    self.store.create(dict(title=path.name,body=content,kind='file',source=path.as_uri(),workspace=workspace));added+=1
                except (ValueError,OSError) as e: failures.append(str(e))
            return f'{added} file(s) captured'+(' · '+failures[0] if failures else '')
        def done(message):self.refresh();self.notify(message)
        if self.store.backend=='python':done(work())
        else:self.asyncTask(work,done)
    @Slot(str)
    def copy(self,ident):
        def done(obj):
            if obj['kind']=='file':
                from qt_mime import QMimeData
                mime=QMimeData();mime.setUrls([QUrl(obj['source'])]);mime.setText(obj['body']);self.app.clipboard().setMimeData(mime)
            else:self.app.clipboard().setText(obj['body'])
            self.notify('Full content copied · switch to any app and paste')
        if self.store.backend=='python':done(self.store.load(ident))
        else:self.asyncTask(lambda:self.store.load(ident),done)
    undoAvailable=Property(bool,lambda s:bool(s._undo),notify=changed)
    @Slot(str)
    def remove(self,ident):
        workspace=self._workspace
        def done(result):
            if result.get('undo'):self._undo=result['undo']
            self.refresh();self.notify('Removed from this collection · Undo is available')
        if self.store.backend=='python':done(self.store.remove(ident,workspace))
        else:self.asyncTask(lambda:self.store.remove(ident,workspace),done)
    @Slot()
    def undoAction(self):
        token=self._undo
        if not token:return
        def done(_):self._undo='';self.refresh();self.notify('Last collection action undone')
        self.asyncTask(lambda:self.store.undo(token),done)
    @Slot(str)
    def openObject(self,ident):
        def done(obj):
            url=obj['source'] if obj['kind']=='file' else obj['body'].strip()
            if obj['kind']=='file':
                try:desktop.local_file(url)
                except (ValueError,OSError):return self.notify('The original file is no longer available')
            elif urlparse(url).scheme not in ('http','https'):return self.notify('Use Copy to copy this text')
            QDesktopServices.openUrl(QUrl(url));self.dismiss()
        self.asyncTask(lambda:self.store.load(ident),done)
    @Slot(object)
    def applyAppCatalog(self,apps):
        if not isinstance(apps,list):return
        self._apps=apps;self.usage.set_catalog(apps);self._iconCache.clear()
        self._dockApps=desktop.dock_groups(self._apps,self._windows,self.preferences.values['pins'])
        self._launcherApps=self.usage.rank(self._apps,self.preferences.values['launcherSort'])
        self.launcherChanged.emit();self.dockLayoutChanged.emit();self.changed.emit()
    @Slot()
    def refreshAppCatalog(self):
        catalog=getattr(self,'appCatalog',None)
        if catalog:catalog.refreshOnOpen()
    @Slot(str)
    def launch(self,ident):
        self.launchApplication(ident)
    @Slot(str)
    def launchForLayout(self,ident):
        group=next((g for g in self._dockApps if g['id']==ident and g['windows']),None)
        if group:
            if len(group['windows'])==1 and group['windows'][0].get('minimized') and self.windowActions:
                target=group['windows'][0]['id'];self.windowTask(target,'restore',lambda:self.windowActions.restore(int(target)));return
            return self.notify('This app already has windows. Restore one from Apps, or open another window in the app, then refresh the layout.')
        self.launchApplication(ident,keep_open=True)
    def launchApplication(self,ident,keep_open=False):
        app=next((a for a in self._apps if a['id']==ident),None)
        if not app:return
        pending=getattr(self,'_pendingAppLaunches',None)
        if pending is None:self._pendingAppLaunches=pending=set()
        if ident in pending:return
        if len(pending)>=8:return self.notify('Wait for the application activation to finish')
        import subprocess
        from app_catalog import launch_result
        environment=desktop.application_environment()
        if self.appearance['matchApps']:
            from application_theme import launch_environment
            environment=launch_environment(self.themeMode,environment)
        try:
            # Keep application processes independent of shell recovery. gio parses
            # desktop field codes and returns when activation is accepted.
            process=subprocess.Popen(['gio','launch',desktop.application_launch_path(app,environment)],env=environment,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError as error:return self.notify('Could not start '+app['name']+': '+str(error)[:120])
        pending.add(ident)
        def accepted(_):
            pending.discard(ident)
            self.recordAppInteraction(ident,'launch')
            if self.panel=='launcher' and not keep_open:self.dismiss()
        def rejected(error):
            pending.discard(ident);self.notify('Could not start '+app['name']+': '+str(error)[:160])
        self.asyncTask(lambda:launch_result(process),accepted,rejected)
    @Slot(object)
    def removableDeviceArrived(self,device):
        if not isinstance(device,dict) or not getattr(self,'systemServices',None):return
        self._deviceNotificationId=getattr(self,'_deviceNotificationId',0)-1
        name=' '.join(str(device.get('name') or 'Removable drive').split())[:100]
        self.systemServices.receiveNotification(dict(id=self._deviceNotificationId,app='Mellipi',summary=name+' connected',body='Open removable devices to mount, open or safely eject it.',actions=[],resident=False,timeout=5000,abstractDevice=True))

    @Slot(object)
    def openNotification(self,note):
        if note.get('abstractDevice') is True and isinstance(note.get('id'),int) and note['id']<0:
            return self.activateSystemAction('removable-devices')
        target=desktop.notification_target(note,self._apps,self._windows)
        if not target:return self.notify('The app for this notification is unavailable')
        if target[0]=='window':self.focusWindow(target[1])
        else:self.launch(target[1])
    @Slot(str,bool)
    def activateDock(self,ident,showAll):
        if ident=="orbit-settings":self.showPanel(self._settingsDestination);return
        group=next((g for g in self._dockApps if g['id']==ident),None)
        if not group:return
        if group['windows']:
            if showAll and len(group['windows'])>1:
                self.showPanel('overview');self._windowFilter=[w['id'] for w in group['windows']];self.windowsChanged.emit()
            else:
                windows=group['windows'];current=next((i for i,w in enumerate(windows) if w.get('active')), -1)
                self.focusWindow(windows[(current+1)%len(windows)]['id'])
        else:self.launch(ident)
    @Slot(str)
    def focusWindow(self,ident):
        if ident=="orbit-settings":
            if self._panel!=self._settingsDestination:self.showPanel(self._settingsDestination)
            return
        target=next((w for w in self._windows if w['id']==ident),None)
        if not target:return
        self.dismiss()
        if wayland_session():
            action=lambda:(self.windowActions.restore(int(ident)),self.xwaylandControls.restore_state(int(ident)) if self.xwaylandControls else None)
        else:action=lambda:desktop.command(['wmctrl','-ia',ident])
        current=next((d['id'] for d in self._desktops if d['active']),target['desktop'])
        if target['desktop']>=0 and target['desktop']!=current:self.dispatchWorkspaceAction(action,1 if target['desktop']>current else -1)
        else:self.windowTask(ident,'focus',action)
    @Slot(int)
    def stepDesktop(self,step):
        spaces=sorted(d['id'] for d in self._desktops)
        if not spaces:return
        current=getattr(self,'_workspaceIntent',None)
        if current not in spaces:current=next((d['id'] for d in self._desktops if d['active']),spaces[0])
        self.switchDesktop(spaces[(spaces.index(current)+(1 if step>0 else -1))%len(spaces)],1 if step>0 else -1)
    @Slot(int)
    def switchDesktop(self,ident,direction=None):
        if ident not in [d['id'] for d in self._desktops]:return
        current=next((d['id'] for d in self._desktops if d['active']),ident)
        if native_session() and getattr(self,'_workspaceIntent',None) is not None:current=self._workspaceIntent
        if ident==current:return
        if native_session():
            self._workspaceIntent=ident
            serial=getattr(self,'_workspaceIntentSerial',0)+1;self._workspaceIntentSerial=serial
            def settled():
                if self._workspaceIntentSerial==serial:self._workspaceIntent=None
            self.windowTask('__workspace__','workspace-intent',lambda:self.windowActions.client.switch_workspace(ident+1,direction=direction if direction in (-1,1) else 1 if ident>=current else -1),settled=settled);return
        if os.environ.get('SWAYSOCK'):
            import sway_events
            action=lambda:sway_events.command(f'workspace number {ident+1}')
        else:action=lambda:desktop.command(['wmctrl','-s',str(ident)])
        self.dispatchWorkspaceAction(action,direction if direction in (-1,1) else 1 if ident>=current else -1)
    def dispatchWorkspaceAction(self,action,direction=None):
        # The native compositor owns live workspace motion. Compatibility/QA
        # backends execute directly; the shell never captures a workspace image.
        if native_session():self.windowTask('__workspace__','native-focus',action)
        else:self.asyncTask(action)
    @Slot()
    def showDesktop(self):
        self.dismiss()
        if native_session():self.windowTask('__desktop__','show',lambda:self.windowActions.client.request('show_desktop'));return
        if os.environ.get('SWAYSOCK'):
            import sway_events;self.dispatchWorkspaceAction(lambda:sway_events.command('workspace number 9'),1)
        else:self.asyncTask(lambda:desktop.command(['wmctrl','-k','on']))
    def refreshWindows(self):
        if wayland_session():return
        if self._polling or not os.environ.get('DISPLAY') or os.environ.get('QT_QPA_PLATFORM')=='offscreen': return
        self._polling=True
        def work():
            from Xlib import display
            connection=display.Display()
            try: return desktop.x11_state(connection)
            finally: connection.close()
        def done(state): self._polling=False; self.applyWindowState(state)
        self.asyncTask(work,done)
    @Slot(object)
    def applyWindowState(self,state):
        if native_session() and self.windowActions:self.windowActions.update(state)
        self.sessionExit.setWindows(state['windows'])
        if self.nativeControlsEnabled and self.xwaylandControls and any(w.get('xid') for w in state['windows']):self.xwaylandControls.start()
        if (self.nativeControlsEnabled or native_session()) and getattr(self,'legacyProxy',None) and any(w.get('xid') for w in state['windows']):self.legacyProxy.start()
        if hasattr(self,'backgroundApps'):self.backgroundApps.observe(self._apps,state['windows'])
        active=next((w['id'] for w in state['windows'] if w.get('active')),None)
        if active!=self._lastUsageWindow:
            self._lastUsageWindow=active
            focused=next((w for w in state['windows'] if w['id']==active),None)
            match=desktop.match_application(focused,self._apps) if focused else None
            if match:self.recordAppInteraction(match['id'],'focus')
        present={w['id'] for w in state['windows']}
        if not native_session() and self.isWayland and self.appearance['frameStyle']=='auto' and present-{w['id'] for w in self._windows}:
            from decoration_policy import apply_auto_decorations
            self.windowTask('__decorations__','auto',apply_auto_decorations)
        self._mru=([active] if active else [])+[i for i in self._mru if i in present and i!=active]
        for window in state['windows']:
            klass=window['klass']
            if klass not in self._iconCache:
                match=desktop.match_application(window,self._apps)
                self._iconCache[klass]=match['icon'] if match else 'application-x-executable'
            window['icon']=self._iconCache[klass]
        if state['windows']!=self._windows or state['desktops']!=self._desktops:
            self._windows=state['windows']; self._desktops=state['desktops']; self._dockApps=desktop.dock_groups(self._apps,self._windows,self.preferences.values['pins']); self.windowsChanged.emit()
            if self.windowActions:
                for window in self._windows:
                    frame=window.get('frame',{});area=window.get('workarea',{})
                    if frame and area and -96<=frame['x']-area['x']<=2 and -96<=frame['y']-area['y']<=2 and -2<=frame['width']-area['width']<=96 and -2<=frame['height']-area['height']<=96:
                        ident=window['id']
                        self.windowTask(ident,'workarea',lambda i=int(ident):self.windowActions.constrain_workarea(i))
    @Slot(str)
    def ask(self,prompt):
        if not self.aiEnabled:return self.notify('AI is disabled for now')
        if self._busy:return
        if not os.environ.get('ORBIT_AI_MODEL'):return self.notify('No model configured. Open System for setup instructions.')
        if not prompt.strip() or len(prompt)>10000:return self.notify('Enter a request under 10,000 characters')
        self._job='pending';self._busy=True;self._answerReady=False;self._answer='';self._earlyAI=[];self.aiChanged.emit()
        selected=self._selected.copy()
        def started(job):
            if self._job!='pending':
                self.asyncTask(lambda:self.store.cancel(job));return
            self._job=job
            events,self._earlyAI=self._earlyAI,[]
            for event in events:self.receiveAI(event)
        def failed(message):self._job='';self._busy=False;self._answer=message;self.aiChanged.emit()
        self.asyncTask(lambda:self.store.ask(prompt,selected),started,failed)
    @Slot(object)
    def receiveAI(self,event):
        if self._job=='pending':self._earlyAI.append(event);return
        if event.get('job')!=self._job:return
        if event['event']=='ai_delta':self._answer+=event['text']
        elif event['event']=='ai_done':self._answer=event['text'];self._answerReady=True;self._busy=False;self._job=''
        elif event['event']=='ai_error':self._answer=event['error'];self._busy=False;self._job=''
        self.aiChanged.emit()
    @Slot()
    def cancelAI(self):
        job=self._job;self._job='';self._busy=False;self._answer='Request cancelled.';self.aiChanged.emit()
        if job and job!='pending':self.asyncTask(lambda:self.store.cancel(job))
    @Slot()
    def saveAnswer(self):
        if self._answerReady and not self._busy:
            data=dict(title='Orbit answer',body=self._answer,kind='result',source='Orbit intelligence',workspace=self._workspace)
            self.asyncTask(lambda:self.store.create(data),lambda _:(self.refresh(),self.notify('Answer saved to the shelf')))
    @Slot()
    def quit(self):
        if self.isWayland:
            self.openExitReview('logout')
        else:self.finishQuit()
    def openExitReview(self,action):
        if not self.sessionExit.enabled:
            self.notify('Session exit is unavailable in this preview');return
        self.sessionExit.setWindows(self._windows)
        if not self.sessionExit.state['active'] or self.sessionExit.state['action']!=action:
            self.sessionExit.openReview(action)
        self.showPanel('session-exit')
    @Slot(str)
    def requestPower(self,action):
        if action not in ('reboot','shutdown'):return
        if not self.sessionExit.enabled:
            self.notify('Power actions require the desktop session');return
        self.openExitReview(action)
    def finishQuit(self):
        action=self.sessionExit.state.get('action','logout')
        if action in ('reboot','shutdown'):
            try:self.systemServices.power(action)
            except Exception as error:self.notify(str(error));return
            self.dismiss();return
        self.quitRequested.emit();self.app.quit()


def configure_x11(window,kind,strut=0,left=0,right=0):
    """Set standard desktop/dock hints without modifying XFCE settings."""
    if wayland_session() or not os.environ.get('DISPLAY') or os.environ.get('QT_QPA_PLATFORM')=='offscreen': return
    try:
        from Xlib import display, X, Xatom
        d=display.Display(); w=d.create_resource_object('window',int(window.winId()))
        atom=d.intern_atom
        w.change_property(atom('_NET_WM_WINDOW_TYPE'),Xatom.ATOM,32,[atom('_NET_WM_WINDOW_TYPE_'+kind)])
        w.change_property(atom('_NET_WM_DESKTOP'),Xatom.CARDINAL,32,[0xffffffff])
        states=[atom('_NET_WM_STATE_STICKY'),atom('_NET_WM_STATE_SKIP_TASKBAR'),atom('_NET_WM_STATE_SKIP_PAGER')]
        if kind=='DESKTOP': states.append(atom('_NET_WM_STATE_BELOW'))
        if kind=='DOCK': states.append(atom('_NET_WM_STATE_ABOVE'))
        w.change_property(atom('_NET_WM_STATE'),Xatom.ATOM,32,states)
        if strut or left or right:
            screen=window.screen().geometry(); top=strut if strut>0 else 0; bottom=-strut if strut<0 else 0
            # Only reserve edges on screens touching the virtual desktop boundary.
            virtual=window.screen().virtualGeometry()
            if screen.x()!=virtual.x():left=0
            if screen.right()!=virtual.right():right=0
            if screen.y()!=virtual.y(): top=0
            if screen.bottom()!=virtual.bottom(): bottom=0
            w.change_property(atom('_NET_WM_STRUT'),Xatom.CARDINAL,32,[left,right,top,bottom])
            w.change_property(atom('_NET_WM_STRUT_PARTIAL'),Xatom.CARDINAL,32,[left,right,top,bottom,screen.y(),screen.bottom(),screen.y(),screen.bottom(),screen.x(),screen.right(),screen.x(),screen.right()])
        d.flush(); d.close()
    except Exception as e: print('X11 hints:',e,flush=True)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--smoke-test',action='store_true'); parser.add_argument('--screenshot'); parser.add_argument('--initial-panel',choices=['launcher','overview','ai','capture','settings','system-settings','quick','music','usage','notifications','tray','bluetooth','battery','screenshot','window-capture','switcher']); args=parser.parse_args()
    if args.smoke_test and os.environ.get('QT_QPA_PLATFORM')=='offscreen':
        # Rendering-only QA must never inherit routing to the user's desktop.
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL'):os.environ.pop(key,None)
    preferences=Preferences()
    from application_theme import cursor_name
    os.environ['XCURSOR_THEME']=cursor_name(preferences.values['mode'])
    os.environ.setdefault('XCURSOR_SIZE','24')
    if preferences.values['profile']=='economy': os.environ.setdefault('QT_QUICK_BACKEND','software')
    QQuickWindow.setDefaultAlphaBuffer(True)
    app=QApplication(sys.argv[:1]); app.setApplicationName('orbit-shell'); app.setQuitOnLastWindowClosed(False)
    # Isolate lock from browser core; no change to user desktop files.
    session_key=__import__('hashlib').sha256((os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY','offscreen')).encode()).hexdigest()[:10]
    if args.smoke_test:session_key='smoke-'+uuid.uuid4().hex[:12]
    state_dir=Path(os.environ.get('ORBIT_DATA',str(ROOT/'data')));state_dir.mkdir(parents=True,mode=0o700,exist_ok=True)
    lock=QLockFile(str(state_dir/f'native-{session_key}.lock'))
    if not lock.tryLock(100): print('Mellipi native shell is already running'); return 1
    core.initialize()
    from icon_theme import configure as configure_icons
    configure_icons()
    store=LazyRustStore()
    bridge=Bridge(app,preferences,store)
    from desktop_tools import DesktopTools
    desktopTools=DesktopTools();desktopTools.notice.connect(bridge.notify);app.aboutToQuit.connect(desktopTools.close)
    from desktop_icons import DesktopIcons
    desktopIcons=DesktopIcons(enabled=bridge.appearance['desktopIcons'],places=not bool(os.environ.get('ORBIT_NESTED')));bridge.desktopIcons=desktopIcons
    desktopIcons.notice.connect(bridge.notify)
    bridge.settingsChanged.connect(lambda:desktopIcons.setEnabled(bridge.appearance['desktopIcons']))
    from system_services import SystemServices
    runtime_services=not args.smoke_test or bool(os.environ.get('ORBIT_TEST_SERVICES'))
    services=SystemServices(enabled=runtime_services);bridge.systemServices=services;services.deviceArrived.connect(bridge.removableDeviceArrived)
    services.notice.connect(bridge.notify)
    services.openNotification.connect(bridge.openNotification)
    from fold_state import FoldController
    foldController=FoldController(app,enabled=not args.smoke_test)
    bridge.foldController=foldController;foldController.notice.connect(bridge.notify)
    from resource_usage import ResourceUsage
    usage=ResourceUsage(enabled=not args.smoke_test);bridge.bindResourceUsage(usage)
    from media import MediaControls
    media=MediaControls(enabled=not args.smoke_test)
    from input_settings import InputSettings
    from idle_policy import IdlePolicy
    from display_controls import DisplayControls
    from shortcut_settings import ShortcutSettings
    from network_controls import NetworkControls
    from power_profiles import PowerProfiles
    native_controls=runtime_services and wayland_session()
    inputs=InputSettings(enabled=native_controls);bridge.inputControls=inputs;inputs.notice.connect(bridge.notify)
    idle=IdlePolicy(preferences,enabled=native_controls);bridge.idlePolicy=idle;idle.notice.connect(bridge.notify)
    bridge.settingsChanged.connect(idle.apply)
    displayControls=DisplayControls(enabled=native_controls);bridge.displayControls=displayControls;displayControls.notice.connect(bridge.notify)
    shortcuts=ShortcutSettings(enabled=native_controls);bridge.shortcutControls=shortcuts;shortcuts.notice.connect(bridge.notify)
    network=NetworkControls(enabled=runtime_services and not os.environ.get('ORBIT_NESTED'));network.notice.connect(bridge.notify)
    powerProfiles=PowerProfiles(enabled=runtime_services and not os.environ.get('ORBIT_NESTED'));powerProfiles.notice.connect(bridge.notify)
    from xwayland_controls import Controls as XwaylandControls
    xwayland=XwaylandControls(enabled=False,actions=bridge.windowActions);bridge.xwaylandControls=xwayland;bridge.nativeControlsEnabled=bool(os.environ.get('SWAYSOCK')) and not args.smoke_test
    from brightness import BrightnessControls
    brightness=BrightnessControls(enabled=not args.smoke_test);bridge.brightnessControls=brightness;brightness.notice.connect(bridge.notify)
    from hardware_keys import HardwareKeys
    hardware=HardwareKeys(services,media,brightness,bridge.notify);bridge.hardwareKey.connect(hardware.handle)
    from bluetooth import BluetoothControls
    bluetooth=BluetoothControls(enabled=not args.smoke_test);bridge.bluetoothControls=bluetooth;bluetooth.notice.connect(bridge.notify)
    from background_apps import BackgroundApps
    background=BackgroundApps(enabled=not args.smoke_test);bridge.backgroundApps=background;background.observe(bridge._apps,bridge._windows);background.restoreHandoff(bridge._apps)
    from power_controls import PowerControls
    power=PowerControls(enabled=runtime_services);bridge.powerControls=power;power.notice.connect(bridge.notify)
    services.update.connect(lambda data:power.refresh() if isinstance(data,dict) and "batteryPercent" in data else None)
    from screenshots import ScreenshotController
    screenshots=ScreenshotController(app,bridge,enabled=not args.smoke_test);bridge.screenshots=screenshots;screenshots.notice.connect(bridge.notify)
    from tray import TrayHost,TrayImages
    trayHost=TrayHost(bridge,enabled=not args.smoke_test);bridge.trayHost=trayHost;trayHost.notice.connect(bridge.notify)
    from legacy_proxy import LegacyProxy
    legacyProxy=LegacyProxy(enabled=native_controls);bridge.legacyProxy=legacyProxy;legacyProxy.notice.connect(bridge.notify)
    bridge.panelChanged.connect(lambda:legacyProxy.start() if bridge.panel=='tray' else None)
    def sync_tray_names():
        known={key[0]:record['app'] for key,record in background.records.items()}
        trayHost.setKnownApps(known)
    bridge.windowsChanged.connect(sync_tray_names);background.changed.connect(sync_tray_names);sync_tray_names()
    trayHost.changed.connect(lambda:background.setExcluded(pids=[r['pid'] for r in trayHost.rows.values() if r.get('pid') and r.get('status')!='Passive']))
    engine=QQmlApplicationEngine(); engine.addImageProvider('icons',Icons());engine.addImageProvider('tray',TrayImages(trayHost));engine.rootContext().setContextProperty('Tray',trayHost);engine.rootContext().setContextProperty('Background',background)
    engine.rootContext().setContextProperty('Orbit',bridge);engine.rootContext().setContextProperty('DesktopFiles',desktopIcons);engine.rootContext().setContextProperty('Usage',usage);engine.rootContext().setContextProperty('System',services);engine.rootContext().setContextProperty('Media',media);engine.rootContext().setContextProperty('Brightness',brightness);engine.rootContext().setContextProperty('Bluetooth',bluetooth);engine.rootContext().setContextProperty('Power',power);engine.rootContext().setContextProperty('Screenshots',screenshots)
    engine.rootContext().setContextProperty('Fold',foldController)
    engine.rootContext().setContextProperty('DesktopTools',desktopTools)
    engine.rootContext().setContextProperty('Arrangements',bridge.arrangements);engine.rootContext().setContextProperty('SessionExit',bridge.sessionExit)
    engine.rootContext().setContextProperty('Input',inputs);engine.rootContext().setContextProperty('Idle',idle);engine.rootContext().setContextProperty('DisplayControls',displayControls)
    engine.rootContext().setContextProperty('Shortcuts',shortcuts);engine.rootContext().setContextProperty('Network',network);engine.rootContext().setContextProperty('PowerProfiles',powerProfiles)
    bridge.displays.changed.connect(displayControls.refresh)
    bridge.panelChanged.connect(lambda:inputs.refresh() if bridge.panel=='system-settings' else None)
    if native_session() and not args.smoke_test:
        from settings_host import SettingsHost
        names=('Orbit','System','Input','Idle','DisplayControls','Shortcuts','Network','PowerProfiles','Power','Bluetooth','Brightness','Media','DesktopTools','Usage')
        bridge.settingsHost=SettingsHost(bridge,{name:engine.rootContext().contextProperty(name) for name in names})
    errors=[];bridge.qmlErrors=errors; engine.warnings.connect(lambda warnings:errors.extend((w.toString() if hasattr(w,"toString") else str(w)) for w in warnings))
    engine.load(QUrl.fromLocalFile(str(ROOT/'native/Desktop.qml')))
    if not engine.rootObjects(): print('\n'.join(errors)); return 1
    root=engine.rootObjects()[0]
    # Top-level QML Windows have no QObject parent. Python-held wrappers and
    # QQuickItem.window() results do not keep their JavaScript ownership roots
    # alive reliably under PySide6 GC. Keep one typed wrapper per native surface
    # and make its lifetime explicit until the engine/application shuts down.
    if QT5:
        from PyQt5.QtQml import QQmlEngine
    else:
        from PySide6.QtQml import QQmlEngine
    native_surfaces=list(root.findChildren(QQuickWindow))
    for surface in native_surfaces:QQmlEngine.setObjectOwnership(surface,QQmlEngine.CppOwnership)
    engine._orbitSurfaceRefs=native_surfaces;bridge._qmlSurfaceRefs=native_surfaces;bridge.shellWindows=native_surfaces
    bridge.settingsChanged.connect(bridge.applyShellCursor)
    windows={name:next(surface for surface in native_surfaces if surface.objectName()==name) for name in ('desktopSurface','topbarSurface','dockSurface','overlaySurface')}
    for surface in native_surfaces:
        if bridge.currentScreen():surface.setScreen(bridge.currentScreen())
    bridge.tooltipWindow=root.findChild(QObject,'tooltipSurface');bridge.contextWindow=root.findChild(QObject,'contextSurface')
    bridge.dockWindow=windows['dockSurface'];bridge.topbarWindow=windows['topbarSurface']
    bridge.panelWindow=windows['overlaySurface']; bridge.desktopWindow=windows['desktopSurface']
    if QT5 and wayland_session():
        from wayland_surfaces import configure
        for name in windows:configure(windows[name],name,bridge.compact,bridge.appearance['dockAlign'],bridge.appearance['shellLayout']=='fold',panel_position=panel_edge(bridge.appearance),floating=bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(bridge.appearance))
        configure(root.findChild(QObject,'dockReserveSurface'),'dockReserveSurface',bridge.compact,spine=bridge.appearance['shellLayout']=='fold',panel_position=panel_edge(bridge.appearance),floating=bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(bridge.appearance))
        configure(root.findChild(QObject,'noticeSurface'),'noticeSurface',bridge.compact)
        configure(bridge.tooltipWindow,'tooltipSurface',bridge.compact)
        configure(bridge.contextWindow,'contextSurface',bridge.compact)
        configure(root.findChild(QObject,'screenshotSelectionSurface'),'screenshotSelectionSurface',bridge.compact)
    bridge._surfacesReady=True;bridge.settingsChanged.emit();bridge.applyWindowTheme()
    if bridge.windowActions:QTimer.singleShot(250,lambda:bridge.windowTask('__layout__','reflow',bridge.windowActions.reflow_maximized))
    for name,kind,reserve in [('desktopSurface','DESKTOP',0),('topbarSurface','DOCK',38),('dockSurface','DOCK',-88)]:
        configure_x11(windows[name],kind,(64 if panel_edge(bridge.appearance)=='top' else -64 if panel_edge(bridge.appearance)=='bottom' else 0) if name=='topbarSurface' and bridge.appearance['shellLayout']=='fold' else 0 if bridge.appearance['shellLayout']=='fold' else (30 if bridge.compact else 38) if reserve>0 else (-62 if bridge.compact else -76) if reserve<0 else 0,left=64 if name=='topbarSurface' and bridge.appearance['shellLayout']=='fold' and panel_edge(bridge.appearance)=='left' else 0,right=64 if name=='topbarSurface' and bridge.appearance['shellLayout']=='fold' and panel_edge(bridge.appearance)=='right' else 0)
    def update_struts(force=False):
        # LayerShellQt commits anchor changes immediately. Do not commit a new
        # edge against the old vertical/horizontal zero-size request; the
        # queued surface move first unmaps/resizes/reconfigures it atomically.
        if not force and QT5 and wayland_session() and (surface_state['moving'] or (panel_edge(bridge.appearance)!=surface_state['position'] or bridge.appearance.get('taskbarFloating',False)!=surface_state['floating'] or bridge.appearance.get('density','compact')!=surface_state['density'])):return
        if QT5 and wayland_session():
            from wayland_surfaces import configure
            configure(windows['desktopSurface'],'desktopSurface',bridge.compact)
            for name in ('topbarSurface','dockSurface'):configure(windows[name],name,bridge.compact,bridge.appearance['dockAlign'],bridge.appearance['shellLayout']=='fold',panel_position=panel_edge(bridge.appearance),floating=bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(bridge.appearance))
            configure(root.findChild(QObject,'dockReserveSurface'),'dockReserveSurface',bridge.compact,spine=bridge.appearance['shellLayout']=='fold',panel_position=panel_edge(bridge.appearance),floating=bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(bridge.appearance))
        bar=bridge.taskbarBodyRect(bridge.screenMap());frame=panel_rect(bridge.screenMap(),bridge.appearance)
        windows['topbarSurface'].setMask(QRegion(bar['x']-frame['x'],bar['y']-frame['y'],bar['width'],bar['height']))
        if bridge.panel:bridge.positionPanel(bridge.panel)
        configure_x11(windows['topbarSurface'],'DOCK',(64 if panel_edge(bridge.appearance)=='top' else -64 if panel_edge(bridge.appearance)=='bottom' else 0) if bridge.appearance['shellLayout']=='fold' else 30 if bridge.compact else 38,left=64 if bridge.appearance['shellLayout']=='fold' and panel_edge(bridge.appearance)=='left' else 0,right=64 if bridge.appearance['shellLayout']=='fold' and panel_edge(bridge.appearance)=='right' else 0)
        configure_x11(windows['dockSurface'],'DOCK',0 if bridge.appearance['shellLayout']=='fold' else -62 if bridge.compact else -76)
    bridge.settingsChanged.connect(update_struts)
    bridge.dockAppsChanged.connect(update_struts)
    surface_state={'screen':bridge.currentScreen(),'geometry':bridge.screenMap(),'compact':bridge.compact,'layout':bridge.appearance['shellLayout'],'density':bridge.appearance.get('density','compact'),'floating':bridge.appearance.get('taskbarFloating',False),'position':panel_edge(bridge.appearance),'moving':False}
    def move_surfaces():
        screen=bridge.currentScreen()
        if screen is None or surface_state['moving']:return
        geometry=bridge.screenMap()
        same_screen=screen is surface_state['screen'] and bridge.appearance['shellLayout']==surface_state['layout'] and panel_edge(bridge.appearance)==surface_state['position'] and bridge.appearance.get('taskbarFloating',False)==surface_state['floating'] and bridge.appearance.get('density','compact')==surface_state['density']
        if screen is surface_state['screen'] and geometry==surface_state['geometry'] and bridge.compact==surface_state['compact'] and bridge.appearance['shellLayout']==surface_state['layout'] and panel_edge(bridge.appearance)==surface_state['position'] and bridge.appearance.get('taskbarFloating',False)==surface_state['floating'] and bridge.appearance.get('density','compact')==surface_state['density']:return
        surface_state['moving']=True;surface_state['screen']=screen;surface_state['geometry']=geometry;surface_state['compact']=bridge.compact;surface_state['layout']=bridge.appearance['shellLayout'];surface_state['position']=panel_edge(bridge.appearance);surface_state['floating']=bridge.appearance.get('taskbarFloating',False);surface_state['density']=bridge.appearance.get('density','compact')
        try:
            bridge.hideTooltip();bridge.closeContext()
            surfaces=root.findChildren(QQuickWindow)
            if QT5 and wayland_session():
                # Same-output geometry/density changes retain the configured
                # native layer roles. Recreating a QWindow's wl_surface here can
                # reuse LayerShellQt configure state and commit before first ack.
                # Moving to a different output still follows the separate output
                # relocation path; ordinary resize never unmaps the desktop.
                if not same_screen:
                    bridge._surfacesReady=False;bridge.settingsChanged.emit()
                    for surface in surfaces:surface.hide();surface.destroy();surface.setScreen(screen)
                # Qt5 can preserve the last compositor-configured dimensions even
                # after recreation. Set the intended native buffer size explicitly.
                windows['dockSurface'].resize(bridge.dockGeometry['surfaceWidth'],bridge.dockGeometry.get('surfaceHeight',66))
                rect=panel_rect(geometry,bridge.appearance);windows['topbarSurface'].resize(rect['width'],rect['height']) if bridge.appearance['shellLayout']=='fold' else windows['topbarSurface'].resize(geometry['width'],38)
                windows['desktopSurface'].resize(geometry['width'],geometry['height'])
                from wayland_surfaces import configure
                for surface in surfaces:configure(surface,surface.objectName(),bridge.compact,bridge.appearance['dockAlign'],bridge.appearance['shellLayout']=='fold',panel_position=panel_edge(bridge.appearance),floating=bridge.appearance.get('taskbarFloating',False),thickness=panel_thickness(bridge.appearance))
                bridge.positionPanel(bridge.panel)
                if not same_screen:bridge._surfacesReady=True;bridge.settingsChanged.emit()
            else:
                for surface in surfaces:surface.setScreen(screen)
                bridge._surfacesReady=True;bridge.settingsChanged.emit()
            update_struts(force=True)
            if bridge.windowActions:QTimer.singleShot(180,lambda:bridge.windowTask('__layout__','reflow',bridge.windowActions.reflow_maximized))
        finally:surface_state['moving']=False
    bridge.displays.changed.connect(move_surfaces)
    bridge.settingsChanged.connect(lambda:QTimer.singleShot(0,move_surfaces))
    from secondary_screens import SecondaryScreens
    secondary=SecondaryScreens(engine,bridge);bridge.secondaryScreens=secondary

    if not args.smoke_test and not wayland_session() and os.environ.get('QT_QPA_PLATFORM')!='offscreen':
        from legacy_tray import LegacyTray
        trayHost.legacy=LegacyTray(trayHost,windows['overlaySurface']);trayHost.changed.emit()
        bridge.panelChanged.connect(lambda:trayHost.showLegacy(bridge.panel=='tray'))
    from control import serve
    bridge.panelChanged.connect(lambda:(bluetooth.stopDiscovery(),bluetooth.cancelPairing()) if bridge.panel!='bluetooth' else None)
    bridge.panelChanged.connect(lambda:services.refreshAudio() if bridge.panel in ('quick','music') and runtime_services else None)
    bridge.panelChanged.connect(lambda:power.refresh() if bridge.panel in ('quick','battery') and runtime_services else None)
    bridge.panelChanged.connect(lambda:brightness.refresh() if bridge.panel=='quick' and runtime_services else None)
    control_server=serve(bridge) if not args.smoke_test else None
    if native_session():
        from native_backend import NativeDesktopEvents
        events=NativeDesktopEvents(bridge)
    elif os.environ.get('SWAYSOCK'):
        from sway_events import SwayEvents
        events=SwayEvents(bridge)
    else:events=DesktopEvents(bridge,shortcuts=not args.smoke_test) if os.environ.get('DISPLAY') and os.environ.get('QT_QPA_PLATFORM')!='offscreen' else None
    signal.signal(signal.SIGTERM,lambda *_:app.quit()); signal.signal(signal.SIGINT,lambda *_:app.quit())
    # Wake Qt only when a Unix signal arrives; no recurring Python heartbeat.
    signal_read,signal_write=os.pipe2(os.O_NONBLOCK)
    previous_wakeup=signal.set_wakeup_fd(signal_write)
    signal_notifier=QSocketNotifier(signal_read,QSocketNotifier.Type.Read,app)
    def drain_signals(*_):
        try: os.read(signal_read,4096)
        except BlockingIOError: pass
    signal_notifier.activated.connect(drain_signals)
    def capture():
        if args.screenshot:
            image=windows['desktopSurface'].grabWindow()
            painter=QPainter(image)
            for name in ('topbarSurface','dockSurface','overlaySurface'):
                window=windows[name]
                if window.isVisible(): painter.drawImage(window.x()-windows['desktopSurface'].x(),window.y()-windows['desktopSurface'].y(),window.grabWindow())
            painter.end(); image.save(args.screenshot)
        if args.smoke_test:
            print(json.dumps({'qml_errors':errors,'apps':len(bridge._apps),'windows':len(bridge._windows),'surfaces':{n:w.isVisible() for n,w in windows.items()},'screenshot':args.screenshot}),flush=True)
            app.exit(1 if errors else 0)
    if args.smoke_test:
        def page(name):
            bridge.showPanel(name)
        def snapshot():
            capture()
        QTimer.singleShot(500,lambda:page('overview'))
        QTimer.singleShot(1200,lambda:page('system-settings'))
        QTimer.singleShot(1550,lambda:page('launcher'))
        QTimer.singleShot(1750,lambda:page('quick'))
        QTimer.singleShot(1900,lambda:page('notifications'))
        QTimer.singleShot(2050,lambda:page('settings'))
        QTimer.singleShot(2250,lambda:page(args.initial_panel or 'launcher'))
        QTimer.singleShot(2900,snapshot)
    else:
        if args.initial_panel: QTimer.singleShot(500,lambda:bridge.showPanel(args.initial_panel))
        if args.screenshot: QTimer.singleShot(1700,capture)
    print('Mellipi native shell ready · Ctrl Alt Space · Ctrl Alt Q to quit',flush=True)
    result=app.exec()
    bridge.tooltipTimer.stop()
    if events: events.close()
    signal_notifier.setEnabled(False); signal.set_wakeup_fd(previous_wakeup); os.close(signal_read); os.close(signal_write)
    if getattr(bridge,'settingsHost',None):bridge.settingsHost.close()
    bridge.sessionExit.close();bridge.appCatalog.close()
    bridge.displays.close()
    secondary.close();hardware.close();inputs.close();idle.close();displayControls.close();shortcuts.close();network.close();powerProfiles.close()
    bridge.pool.shutdown(wait=True,cancel_futures=True)
    bridge.closeWindowTasks()
    usage.close()
    desktopIcons.close()
    foldController.close()
    screenshots.close()
    power.close()
    background.close()
    bluetooth.close()
    brightness.close()
    xwayland.close()
    media.close()
    legacyProxy.close();trayHost.close()
    services.close()
    store.close()
    for window in app.topLevelWindows(): window.hide()
    engine.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete) # DeferredDelete: tear down QML while its context still exists.
    return result

if __name__=='__main__': sys.exit(main())

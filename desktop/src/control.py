"""User-only local control channel for compositor shortcuts."""
import hashlib,os,json
from pathlib import Path

def socket_path():
    session=os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY','desktop')
    key=hashlib.sha256(session.encode()).hexdigest()[:12]
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR','/tmp'))/f'orbit-{os.getuid()}'
    runtime.mkdir(mode=0o700,exist_ok=True)
    if runtime.stat().st_uid!=os.getuid():raise PermissionError('Invalid Orbit runtime directory owner')
    runtime.chmod(0o700)
    return str(runtime/f'control-{key}')

def serve(bridge):
    from qt_compat import QLocalServer,QObject
    server=QLocalServer(bridge);server.setSocketOptions(QLocalServer.UserAccessOption)
    # PyQt's native signal connection is not a Python GC root. Without an
    # explicit owner, the socket/read closure cycle can be collected while Qt
    # still holds a callable pointer (including from a different worker thread).
    server._activeClients={}
    path=socket_path();QLocalServer.removeServer(path)
    if not server.listen(path):raise RuntimeError(server.errorString())
    def find_item(window,name):
        if not window:return None
        found=window.findChild(QObject,name)
        if found:return found
        pending=[window.contentItem()];visited=0
        while pending and visited<4096:
            item=pending.pop();visited+=1
            if item.objectName()==name:return item
            pending.extend(item.childItems())
        return None
    def connected():
        connection=server.nextPendingConnection()
        if connection is None:return
        if len(server._activeClients)>=64:
            connection.disconnectFromServer();connection.deleteLater();return
        buffer=bytearray()
        def read():
            buffer.extend(bytes(connection.readAll()))
            if len(buffer)>256:connection.disconnectFromServer();return
            if b"\n" not in buffer:return
            data=bytes(buffer).decode('utf-8','replace').strip()
            if data=='status':
                connection.write(json.dumps({
                    'app_usage_tracker':type(bridge.usage).__name__,
                    'resource_monitor':type(bridge.resourceUsage).__name__,
                    'shell_layout':bridge.appearance.get('shellLayout','classic'),
                    'display_settings':getattr(bridge,'displayControls',None).state if getattr(bridge,'displayControls',None) else {},
                    'input_settings':getattr(bridge,'inputControls',None).state if getattr(bridge,'inputControls',None) else {},
                    'idle_policy':getattr(bridge,'idlePolicy',None).state if getattr(bridge,'idlePolicy',None) else {},
                    'secondary_screens':getattr(bridge,'secondaryScreens',None).state if getattr(bridge,'secondaryScreens',None) else [],
                    'shell_window_count':len(getattr(bridge,'shellWindows',())),
                    'legacy_proxy':getattr(bridge,'legacyProxy',None).state if getattr(bridge,'legacyProxy',None) else {},
                    'topbar_connected':bridge.appearance.get('topbarConnected',False),
                    'fold_available':getattr(bridge,'foldController',None) is not None,
                    'dock_native':{'width':bridge.dockWindow.width() if bridge.dockWindow else 0,'height':bridge.dockWindow.height() if bridge.dockWindow else 0},
                    'topbar_native':{'width':bridge.topbarWindow.width(),'height':bridge.topbarWindow.height()},
                    'panel_mask':getattr(bridge,'_panelMask',{}),
                    'frame_controls':{}, # retired detached controls; retained status compatibility
                    'native_window_controls':bridge.xwaylandControls.status if bridge.xwaylandControls else {},
                    'desktop_icons':{'enabled':bridge.appearance['desktopIcons'],'count':len(bridge.desktopIcons.items)},
                    'panel_geometry':{'width':bridge.panelWindow.width() if bridge.panelWindow else 0,'height':bridge.panelWindow.height() if bridge.panelWindow else 0,'active':bridge.panelWindow.isActive() if bridge.panelWindow else False},
                    'dock_geometry':bridge.dockGeometry,
                    'dock_mask':bridge._dockMask,
                    'ai_enabled':bridge.aiEnabled,
                    'screenshots':bridge.screenshots.state,
                    'power':bridge.powerControls.state,
                    'launcher_sort':bridge.appearance['launcherSort'],
                    'bluetooth':{'available':bridge.bluetoothControls.state['available'],'powered':bridge.bluetoothControls.state['powered'],'device_count':len(bridge.bluetoothControls.devices)},
                    'brightness':bridge.brightnessControls.state,
                    'external_displays':bridge.brightnessControls.externalDisplays,
                    'background_watches':len(bridge.backgroundApps.records),
                    'background_apps':[{'name':r['name'],'id':r['id']} for r in bridge.backgroundApps.items],
                    'outputs':bridge.outputs,
                    'selected_output':bridge.selectedOutput,
                    'screen_geometry':bridge.screenGeometry,
                    'tray':[{'name':r['name'],'status':r['status']} for r in bridge.trayHost.items],
                    'backend':bridge.store.backend,
                    'wayland':bridge.isWayland,
                    'workspace':next((row['id']+1 for row in bridge._desktops if row.get('active')),None),
                    'panel':bridge.panel,
                    'session_exit':bridge.sessionExit.state,
                    'settings_window':{'ready':getattr(getattr(bridge,'settingsHost',None),'ready',False),'errors':getattr(getattr(bridge,'settingsHost',None),'errors',[])},
                    'notice':bridge.notice,
                    'mode':bridge.themeMode,
                    'switching':bridge._switchActive,
                    'switch_index':bridge._switchIndex,
                    'tooltip':bridge._tooltip,
                    'context_open':bool(bridge._context),
                    'shortcuts':bridge.shortcutStatus,
                    'qml_errors':getattr(bridge,'qmlErrors',[]),
                    'dock':[{'name':g['name'],'windows':len(g['windows'])} for g in bridge._dockApps],
                }).encode());connection.flush()
            elif data=='prepare-reload':
                fold=getattr(bridge,'foldController',None)
                if fold:fold.flush()
                background=getattr(bridge,'backgroundApps',None)
                saved=background.saveHandoff() if background else True
                connection.write(json.dumps({'ok':not getattr(fold,'_dirty',False) and saved}).encode());connection.flush()
            elif data.startswith('qa-arrangement-') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                action=data.removeprefix('qa-arrangement-');model=bridge.arrangements
                if action=='state':
                    connection.write(json.dumps(dict(layouts=model.layouts,preview=model.preview,undo=model.undoLabel,busy=model.busy)).encode());connection.flush()
                elif action=='save':model.save('QA layout')
                elif action=='preview' and model.layouts:model.openPreview(model.layouts[0]['id'])
                elif action=='apply':model.apply()
                elif action=='undo':model.undo()
                elif action.startswith('snap:'):
                    parts=action.split(':')
                    if len(parts)==3 and parts[1].isdigit() and parts[2] in ('left','right'):bridge.arrangeWindow(parts[1],parts[2])
            elif data=='qa-tray-activate-first' and os.environ.get('ORBIT_QA')=='1':
                items=bridge.trayHost.items
                if items:bridge.trayHost.activate(items[0]['key'],100,100);bridge.dismiss()
            elif data.startswith('qa-output-item:') and os.environ.get('ORBIT_QA')=='1':
                _,output_name,name=data.split(':',2)
                for window in bridge.shellWindows:
                    belongs=window.property('orbitOutputName')==output_name or (not window.property('orbitOutputName') and output_name==bridge.selectedOutput)
                    if belongs and window.isVisible():
                        item=find_item(window,name)
                        if item:
                            point=bridge.itemScreenPoint(item,0,0);point.update(width=item.width(),height=item.height(),visible=item.isVisible(),enabled=item.isEnabled())
                            connection.write(json.dumps(point).encode());connection.flush();break
            elif data.startswith('qa-shell-item:') and os.environ.get('ORBIT_QA')=='1':
                name=data[len('qa-shell-item:'):];found=[]
                for window in getattr(bridge,'shellWindows',()):
                    if not window.isVisible():continue
                    pending=[window.contentItem()]
                    while pending:
                        item=pending.pop()
                        if item.objectName()==name and item.isVisible():found.append(item)
                        pending.extend(item.childItems())
                if found:
                    item=found[0];point=bridge.itemScreenPoint(item,0,0)
                    point.update(width=item.width(),height=item.height(),visible=item.isVisible(),enabled=item.isEnabled())
                    for key in ('text','section','contentHeight','availableHeight','implicitHeight','value'):
                        value=item.property(key)
                        if isinstance(value,(str,int,float,bool)):point[key]=value
                    connection.write(json.dumps(point).encode());connection.flush()
            elif data=='qa-fold-state' and os.environ.get('ORBIT_QA')=='1':
                fold=getattr(bridge,'foldController',None)
                connection.write(json.dumps({'state':fold.state,'items':fold.items} if fold else {}).encode());connection.flush()
            elif data.startswith('qa-fold-item:') and os.environ.get('ORBIT_QA')=='1':
                item=find_item(bridge.panelWindow,data[len('qa-fold-item:'):])
                if item:
                    point=bridge.itemScreenPoint(item,0,0)
                    point.update(width=item.width(),height=item.height(),visible=item.isVisible(),enabled=item.isEnabled())
                    text=item.property('text')
                    if isinstance(text,str):point['text']=text
                    connection.write(json.dumps(point).encode());connection.flush()
            elif data.startswith('qa-system-action:') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                action=data.removeprefix('qa-system-action:')
                if action in ('density','pointer','microphone','brightness','battery-health','wallpaper','reduced-motion','screenshot','do-not-disturb','settings'):bridge.activateSystemAction(action)
            elif data.startswith('qa-density:') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                value=data.removeprefix('qa-density:')
                if value in ('comfortable','compact','extra'):bridge.setPreference('density',value)
            elif data.startswith('qa-taskbar-style:') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                parts=data.removeprefix('qa-taskbar-style:').split(':')
                if len(parts)==3 and parts[0] in ('full','fit') and parts[1] in ('0','1') and parts[2] in ('square','soft','rounded'):
                    bridge.setPreference('taskbarLength',parts[0]);bridge.setPreference('taskbarFloating',parts[1]=='1');bridge.setPreference('corners',parts[2])
            elif data.startswith('qa-taskbar-position:') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                position=data.removeprefix('qa-taskbar-position:')
                if position in ('left','right','top','bottom'):bridge.setPreference('panelPosition',position)
            elif data.startswith('qa-settings-') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                action=data.removeprefix('qa-settings-')
                if action=='dismiss':bridge.dismiss()
                elif action=='resume':bridge.activateDock('orbit-settings',False)
                elif action=='close':bridge.closeSettingsTask()
            elif data.startswith('qa-essential-tool:') and os.environ.get('ORBIT_QA')=='1' and os.environ.get('ORBIT_NESTED')=='1':
                name=data.removeprefix('qa-essential-tool:')
                if name in ('users','datetime','recovery'):
                    tool=getattr(bridge,'desktopTools',None)
                    if tool:tool.open(name)
                elif name=='choose-folder':
                    recovery=getattr(bridge,'recovery',None)
                    if recovery:recovery.chooseDirectory('backupParent')
            elif data=='qa-window-state' and os.environ.get('ORBIT_QA')=='1':
                connection.write(json.dumps({'windows':bridge._windows,'frame_style':bridge.appearance['frameStyle'],'tracking':bridge.frameTrackingEnabled}).encode());connection.flush()
            elif data.startswith('qa-system-section:') and os.environ.get('ORBIT_QA')=='1':
                value=data.removeprefix('qa-system-section:')
                if value.isdigit() and 0<=int(value)<=17:
                    if getattr(bridge,'settingsHost',None):bridge.rememberSettingsSection(int(value))
                    else:
                        item=find_item(bridge.panelWindow,'systemSettingsPanel')
                        if item:item.setProperty('section',int(value))
            elif data=='qa-panel-state' and os.environ.get('ORBIT_QA')=='1':
                window=bridge.panelWindow;owner=window.parent() if window else None
                values={'visible':window.isVisible() if window else False,'exposed':window.isExposed() if window else False,'requested':bridge._panelGeometry}
                if owner:
                    for key in ('renderedPanel','overlayShown','panelWidth','panelHeight'):values[key]=owner.property(key)
                connection.write(json.dumps(values).encode());connection.flush()
            elif data.startswith('qa-quick-tab-') and data[13:] in ('0','1','2') and os.environ.get('ORBIT_QA')=='1':
                quick=find_item(bridge.panelWindow,'quickPanel')
                if quick:quick.setProperty('section',int(data[13:]))
            elif data=='qa-shot-screen' and os.environ.get('ORBIT_QA')=='1':bridge.screenshots.captureScreen()
            elif data=='qa-shot-window' and os.environ.get('ORBIT_QA')=='1':bridge.screenshots.captureActiveWindowForQA()
            elif data=='qa-shot-area' and os.environ.get('ORBIT_QA')=='1':
                r=bridge.currentScreen().geometry();bridge.screenshots.beginArea();bridge.screenshots.captureArea(r.x()+30,r.y()+60,180,120)
            elif data=='qa-shot-select' and os.environ.get('ORBIT_QA')=='1':bridge.screenshots.beginArea()
            elif data=='qa-shot-cancel' and os.environ.get('ORBIT_QA')=='1':bridge.screenshots.cancelArea()
            elif data=='qa-tip' and os.environ.get('ORBIT_QA')=='1':
                r=bridge.app.primaryScreen().geometry();bridge.queueTooltip('Tooltip below the top bar',r.right()-16,r.y()+24)
            elif data=='qa-close-tip' and os.environ.get('ORBIT_QA')=='1':bridge.hideTooltip()
            elif data=='qa-menu' and os.environ.get('ORBIT_QA')=='1':
                r=bridge.app.primaryScreen().geometry();bridge.openContext('desktop','',r.x()+30,r.y()+50)
            elif data=='qa-dock-menu' and os.environ.get('ORBIT_QA')=='1':
                groups=bridge._dockApps
                if groups:
                    screen=bridge.screenMap();g=bridge.dockGeometry;alignment=bridge.appearance['dockAlign']
                    left=12 if alignment=='left' else screen['width']-g['bodyWidth']-12 if alignment=='right' else (screen['width']-g['bodyWidth'])/2
                    bridge.openDockContext(groups[0]['id'],round(screen['x']+left+g['padding']+g['slot']+g['gap']+g['slot']/2),screen['y']+screen['height']-(52 if bridge.compact else 66)-10)
            elif data=='qa-context-geometry' and os.environ.get('ORBIT_QA')=='1':
                item=find_item(bridge.contextWindow,'contextPopup')
                if item:connection.write(json.dumps({key:item.property(key) for key in ('x','y','width','height')}).encode());connection.flush()
            elif data=='qa-app-menu' and os.environ.get('ORBIT_QA')=='1':
                item=find_item(bridge.panelWindow,'launcherAppRow')
                if item:
                    value=item.property('modelData');value=value.toVariant() if hasattr(value,'toVariant') else value
                    bridge.openPanelContext(item,'app',value['id'],20,20)
            elif data=='qa-close-menu' and os.environ.get('ORBIT_QA')=='1':bridge.closeContext()
            elif data in ('qa-light','qa-dark') and os.environ.get('ORBIT_QA')=='1':bridge.setPreference('mode',data.removeprefix('qa-'))
            elif data in ('qa-compact','qa-comfortable') and os.environ.get('ORBIT_QA')=='1':bridge.setPreference('compact',data=='qa-compact')
            elif data in ('qa-layout-classic','qa-layout-fold') and os.environ.get('ORBIT_QA')=='1':bridge.setPreference('shellLayout',data.removeprefix('qa-layout-'))
            elif data=='qa-high-contrast' and os.environ.get('ORBIT_QA')=='1':bridge.setPreference('highContrast',True)
            elif data.startswith('qa-text-scale:') and os.environ.get('ORBIT_QA')=='1':
                try:bridge.setPreference('textScale',float(data.split(':',1)[1]))
                except ValueError:pass
            elif data=='switch-next':bridge.cycleSwitch(1)
            elif data=='switch-prev':bridge.cycleSwitch(-1)
            elif data=='switch-accept':bridge.acceptSwitch()
            elif data=='switch-cancel':bridge.cancelSwitch()
            elif data.startswith('workspace:') and data[10:].isdigit() and 1<=int(data[10:])<=10:bridge.switchDesktop(int(data[10:])-1)
            elif data.startswith('output:'):bridge.setPreference('output',data[7:])
            elif data=='brightness-detect':bridge.brightnessControls.discoverExternal()
            elif data.startswith('brightness-select:') and data[18:].isdigit():bridge.brightnessControls.selectExternal(int(data[18:]))
            elif data.startswith('brightness-set:') and data[15:].isdigit() and 1<=int(data[15:])<=100:bridge.brightnessControls.setBrightness(int(data[15:]))
            elif data=='quit':bridge.quit()
            elif data in ('fold','launcher','ai','settings','system-settings','overview','quick','music','usage','notifications','tray','bluetooth','battery','screenshot','capture'):bridge.showPanel(data)
            connection.disconnectFromServer()
        key=id(connection)
        server._activeClients[key]=(connection,read)
        def destroyed(*_):server._activeClients.pop(key,None)
        connection.destroyed.connect(destroyed)
        connection.readyRead.connect(read);connection.disconnected.connect(connection.deleteLater)
        if connection.bytesAvailable():read()
    server.newConnection.connect(connected)
    return server

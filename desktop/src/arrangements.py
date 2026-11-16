"""Bounded, on-demand arrangement history and private reusable layouts.

No titles, contents, screenshots or background sampling are saved. Runtime undo
uses live client identity; saved layouts require explicit matching before apply.
"""
import copy,json,math,os,stat,tempfile,threading,uuid,time,sys
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot,QTimer
from window_actions import find_window,valid_rect

def client_key(node):
    return (node.get('pid',0),node.get('app_id') or (node.get('window_properties') or {}).get('class',''),node.get('window',0))

def bounded_rect(rect,area):
    w=min(rect['width'],area['width']);h=min(rect['height'],area['height'])
    return dict(x=max(area['x'],min(rect['x'],area['x']+area['width']-w)),y=max(area['y'],min(rect['y'],area['y']+area['height']-h)),width=w,height=h)

def map_geometry(rect,area):
    if not valid_rect(rect) or not valid_rect(area):return {}
    rect=bounded_rect(rect,area)
    return dict(x=(rect['x']-area['x'])/area['width'],y=(rect['y']-area['y'])/area['height'],
                w=rect['width']/area['width'],h=rect['height']/area['height'])

def space_map(desktops,windows,current):
    grouped={row['id']:[] for row in desktops}
    for window in windows:
        group=grouped.get(window.get('desktop'))
        if group is not None and not window.get('transient'):
            group.append(window)
    spaces=[]
    for workspace in sorted(desktops,key=lambda row:row['id']):
        ident=workspace['id']; windows=grouped[ident]; shown=[]
        for row in windows[:48]:
            minimized=bool(row.get('minimized'))
            shown.append(dict(id=str(row['id']),name=row.get('title') or row.get('klass') or 'Window',
                              icon=row.get('icon') or 'application-x-executable',minimized=minimized,
                              tile={} if minimized else map_geometry(row.get('rect'),row.get('workarea'))))
        name=workspace.get('name','')
        spaces.append(dict(id=ident,name=name if name and not name.isdecimal() else f'Space {ident+1}',
                           active=ident==current,count=len(windows),windows=shown,
                           tiles=[row for row in shown if row['tile']][:9]))
    return spaces

def checkpoint_preview(entry,windows):
    live={str(row['id']):row for row in windows}
    result=[];groups={}
    for row in entry['rows']:
        key=row['key']; current=live.get(str(row['id']))
        matches=bool(current and not current.get('minimized') and current.get('pid',0)==key[0]
                     and (current.get('klass') or 'native-window').casefold()==str(key[1]).casefold())
        item=dict(id=str(row['id']),name=(current.get('title') if matches else '') or key[1] or 'Window',
                  workspace=row['desktop'],status='Restore position' if matches else 'No matching open window',
                  available=matches,tile=map_geometry(row['rect'],row['area']),
                  icon=(current.get('icon') if matches else '') or 'application-x-executable')
        result.append(item)
        output=row.get('output','')
        groups.setdefault((row['desktop'],output),[]).append(item)
    return dict(id=entry['id'],label=entry['label'],rows=result,
                spaces=[dict(workspace=space,tiles=tiles[:9]) for (space,_),tiles in groups.items()],
                available=sum(row['available'] for row in result))

def layout_cards(layouts, apps):
    """Small geometry-only previews. No window thumbnails or private titles."""
    icons = {app['id']: app.get('icon') or 'application-x-executable' for app in apps}
    cards = []
    for layout in layouts:
        windows = layout['windows']
        first = windows[0]
        tiles = []
        for row in windows:
            if (row['desktop'], row['output']) != (first['desktop'], first['output']):
                continue
            tiles.append(dict(map_geometry(row['rect'],row['area']),
                              icon=icons.get(row['app'], 'application-x-executable')))
        cards.append(dict(id=layout['id'], name=layout['name'], count=len(windows), tiles=tiles))
    return cards


class ArrangementEngine:
    def __init__(self,actions,path):
        self.actions=actions;self.path=Path(path);self.history=[];self.layouts=[];self.lock=threading.RLock();self.sync=None;self.load()
    def capture(self,ids=None):
        tree=self.actions.request(4);rows=[]
        def walk(node,space=None,output=''):
            if node.get('type')=='output':output=node.get('name','')
            if node.get('type')=='workspace':space=node
            if (node.get('app_id') or node.get('window')) and space and 1<=space.get('num',0)<=99 and node.get('pid')!=os.getpid():
                ident=node['id'];found=find_window(tree,ident)
                if found and (ids is None or ident in ids):
                    target,_=found;rect=target['_outer_rect'];area=space.get('rect',{})
                    if valid_rect(rect) and valid_rect(area):
                        rows.append(dict(id=ident,key=client_key(node),rect=dict(rect),area=dict(area),desktop=space['num'],output=output,floating=bool(target['_floating']),snap=node.get('snap'),fullscreen=bool(node.get('fullscreen_mode')),focused=bool(node.get('focused')),saved=copy.deepcopy(self.actions.saved.get(ident)),snapped=copy.deepcopy(self.actions.snapped.get(ident))))
            for child in node.get('nodes',[])+node.get('floating_nodes',[]):walk(child,space,output)
        walk(tree);return rows[:48]
    def record_action(self,label,fn,ids=None):
        with self.lock,self.actions.lock:
            before=self.capture(ids)
            try:return fn()
            finally:
                # Retain partial changes too, so a failed multi-action is recoverable.
                action_failed=sys.exc_info()[0] is not None
                try:after=self.capture(ids)
                except Exception:
                    if before:self.record_checkpoint(label,before)
                    # Do not replace the original operation error with an IPC
                    # failure while checking its result.
                    if not action_failed:raise
                else:
                    if before and before!=after:self.record_checkpoint(label,before)
    def record_checkpoint(self,label,rows):
        self.history=(self.history+[dict(id=uuid.uuid4().hex,label=label,rows=rows)])[-10:]
    def restore_checkpoint(self,ident):
        with self.lock,self.actions.lock:
            entry=next((row for row in self.history if row['id']==ident),None)
            if entry is None:raise ValueError('Checkpoint is no longer available')
            rows=entry['rows']
            return self.record_action('Restore '+entry['label'],lambda:self.restore_rows(rows,True),
                                      {row['id'] for row in rows})
    def _areas(self):
        tree=self.actions.request(4);areas={}
        def walk(n):
            if n.get('type')=='workspace' and 1<=n.get('num',0)<=99 and valid_rect(n.get('rect')):areas[n['num']]=n['rect']
            for c in n.get('nodes',[])+n.get('floating_nodes',[]):walk(c)
        walk(tree)
        if not areas:raise ValueError('No workspace is available')
        return areas
    def restore_rows(self,rows,undo=False):
        count=0;skipped=0;areas=self._areas();focus=None
        for row in rows:
            found=find_window(self.actions.request(4),row['id'])
            if not found or tuple(row['key'])!=client_key(found[0]):skipped+=1;continue
            ident=row['id'];desktop=row['desktop']
            # Moving creates an empty numbered workspace on Sway. Read its real
            # workarea afterwards, including a changed or removed monitor.
            self.actions.command(f'[con_id={ident}] fullscreen disable; [con_id={ident}] move container to workspace number {desktop}')
            areas=self._areas()
            if desktop not in areas:
                desktop=min(areas);self.actions.command(f'[con_id={ident}] move container to workspace number {desktop}')
            area=areas[desktop]
            native=getattr(self.actions,'client',None)
            output=None
            if native and row.get('output'):
                output=next((item for item in native.snapshot().get('outputs',[]) if item['name']==row['output']),None)
                if output:area=output['workarea']
            if undo and row['area']==area:rect=bounded_rect(row['rect'],area)
            else:
                prior=row['area'];r=row['rect']
                rect=bounded_rect(dict(x=area['x']+round((r['x']-prior['x'])/prior['width']*area['width']),y=area['y']+round((r['y']-prior['y'])/prior['height']*area['height']),width=max(1,round(r['width']/prior['width']*area['width'])),height=max(1,round(r['height']/prior['height']*area['height']))),area)
            if output:
                native.request('resize',id=ident,rect=rect,output=output['name'])
            else:
                self.actions._resize(ident,rect)
            if native and row.get('snap') and row['snap']!='maximize':
                native.request('snap',id=ident,side=row['snap'],**({'output':output['name']} if output else {}))
            # Sway versions differ on whether floating resize includes the CSD
            # frame. Measure one configure reply rather than accumulating borders.
            time.sleep(.04)
            measured=find_window(self.actions.request(4),ident)
            if measured and not row.get('snap'):
                actual=measured[0]['_outer_rect'];dw=actual['width']-rect['width'];dh=actual['height']-rect['height']
                if (dw or dh) and 0<=dw<=64 and 0<=dh<=128 and rect['width']>dw and rect['height']>dh:
                    self.actions.command(f'[con_id={ident}] resize set width {rect["width"]-dw} px height {rect["height"]-dh} px; [con_id={ident}] move absolute position {rect["x"]} px {rect["y"]} px')
            if undo and not row['floating']:self.actions.command(f'[con_id={ident}] floating disable')
            if row.get('fullscreen'):self.actions.command(f'[con_id={ident}] fullscreen enable')
            for table,key in ((self.actions.saved,'saved'),(self.actions.snapped,'snapped')):
                table.pop(ident,None)
                if undo and row.get(key):table[ident]=copy.deepcopy(row[key])
            if row.get('focused'):focus=ident
            count+=1
        self.actions._maximized=frozenset(self.actions.saved);self.actions._persist()
        if self.sync:
            for row in rows:self.sync(row['id'])
        if focus:self.actions.command(f'[con_id={focus}] focus')
        return dict(applied=count,skipped=skipped)
    def undo(self):
        with self.lock,self.actions.lock:
            if not self.history:raise ValueError('There is no arrangement to undo')
            result=self.restore_rows(self.history[-1]['rows'],True);self.history=self.history[:-1];return result
    def save(self,name,identities,folder=""):
        name=name.strip()
        folder=folder.strip()
        if folder and (len(folder)>4096 or any(ord(c)<32 for c in folder)
                       or not Path(folder).expanduser().is_absolute()
                       or not Path(folder).expanduser().is_dir()):
            raise ValueError('Enter an existing folder with an absolute path')
        folder=str(Path(folder).expanduser()) if folder else ''

        if not name or len(name)>48 or any(ord(c)<32 for c in name):raise ValueError('Use a layout name of 1–48 characters')
        with self.lock,self.actions.lock:
            rows=self.capture();saved=[]
            for row in rows:
                app=identities.get(str(row['id']))
                if not app:continue
                saved.append(dict(app=app,klass=str(row['key'][1])[:256],rect=row['rect'],area=row['area'],desktop=row['desktop'],output=row['output'],snap=row['snap'],floating=row['floating'],fullscreen=row['fullscreen']))
            if not saved:raise ValueError('No recognized application windows to save')
            if len(saved)>24:raise ValueError('Save layouts with at most 24 application windows')
            if len(self.layouts)>=12:raise ValueError('Remove a saved layout first (limit 12)')
            self.layouts.append(dict(id=uuid.uuid4().hex,name=name,windows=saved,folder=folder))
            try:self.persist()
            except Exception:self.layouts.pop();raise
            return len(saved)
    def remove(self,ident):
        with self.lock:
            previous=self.layouts;self.layouts=[r for r in previous if r['id']!=ident]
            try:self.persist()
            except Exception:self.layouts=previous;raise
    def preview(self,ident,windows,apps):
        saved=next((r for r in self.layouts if r['id']==ident),None)
        if saved is None:raise ValueError('Layout is no longer available')
        rows=[];used=set()
        for index,row in enumerate(saved['windows']):
            app=next((a for a in apps if a['id']==row['app']),None)
            candidates=[dict(id=str(w['id']),name=w.get('title') or row['app'],pid=w.get('pid',0)) for w in windows if not w.get('minimized') and w.get('appId')==row['app'] and str(w['id']) not in used]
            selected=candidates[0]['id'] if len(candidates)==1 else ''
            if selected:used.add(selected)
            rows.append(dict(index=index,app=row['app'],workspace=row['desktop'],name=app['name'] if app else row['app'],candidates=candidates,selected=selected,installed=bool(app),status='Reuse open window' if selected else 'Choose a window' if candidates else 'Open another window' if any(w.get('appId')==row['app'] and not w.get('minimized') for w in windows) else 'Open application first' if app else 'Application is not installed'))
        return dict(id=ident,name=saved['name'],rows=rows,folder=saved.get('folder',''))
    def apply(self,preview):
        saved=next((r for r in self.layouts if r['id']==preview['id']),None)
        if not saved:raise ValueError('Layout is no longer available')
        ids=[int(r['selected']) for r in preview['rows'] if r['selected']]
        if len(ids)!=len(preview['rows']) or len(set(ids))!=len(ids):raise ValueError('Choose a different open window for each slot')
        live={r['id']:r for r in self.capture(ids)};rows=[]
        for choice,layout in zip(preview['rows'],saved['windows']):
            current=live.get(int(choice['selected']))
            if not current:raise ValueError('A selected window closed; refresh the preview')
            candidate=next((row for row in choice['candidates'] if row['id']==choice['selected']),None)
            if candidate is None or (candidate.get('pid') and candidate['pid']!=current['key'][0]):raise ValueError('A selected window changed; refresh the preview')
            # Verify class again: an ID must never silently select another client.
            if str(current['key'][1])!=layout['klass']:raise ValueError('A selected application changed; refresh the preview')
            rows.append(dict(current,rect=layout['rect'],area=layout['area'],desktop=layout['desktop'],output=layout.get('output',''),snap=layout.get('snap'),floating=True,fullscreen=layout['fullscreen'],focused=False))
        return self.record_action('Apply '+saved['name'],lambda:self.restore_rows(rows),ids)
    def load(self):
        try:
            st=self.path.lstat()
            if not stat.S_ISREG(st.st_mode) or self.path.is_symlink() or st.st_uid!=os.getuid() or st.st_size>131072 or st.st_mode&0o077:return
            data=json.loads(self.path.read_text())
            if not isinstance(data,dict):return
            if data.get('version')!=1 or not isinstance(data.get('layouts'),list) or len(data['layouts'])>12:return
            rows=data['layouts']
            for layout in rows:
                if not isinstance(layout,dict) or not isinstance(layout.get('id'),str) or len(layout['id'])!=32 or not isinstance(layout.get('name'),str) or not 1<=len(layout['name'])<=48:raise ValueError('Invalid saved layout')
                folder=layout.get('folder','')
                if not isinstance(folder,str) or len(folder)>4096 or (folder and (not Path(folder).is_absolute() or any(ord(c)<32 for c in folder))):
                    raise ValueError('Invalid project folder')
                if not isinstance(layout.get('windows'),list) or not 1<=len(layout['windows'])<=24:raise ValueError('Invalid saved layout windows')
                for row in layout['windows']:
                    if not isinstance(row,dict) or not valid_rect(row.get('rect')) or not valid_rect(row.get('area')) or type(row.get('desktop')) is not int or not 1<=row['desktop']<=99 or not all(isinstance(row.get(k),str) and 0<len(row[k])<=256 for k in ('app','klass')) or type(row.get('fullscreen')) is not bool or type(row.get('floating')) is not bool:raise ValueError('Invalid saved layout window')
                    if not isinstance(row.get('output',''),str) or len(row.get('output',''))>128 or row.get('snap') not in (None,'left','right','top','bottom','top-left','top-right','bottom-left','bottom-right','maximize'):
                        raise ValueError('Invalid saved output or tile')
            self.layouts=rows
        except (OSError,ValueError,TypeError,KeyError):pass
    def persist(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.is_symlink():raise ValueError('Layout destination cannot be a link')
        fd,name=tempfile.mkstemp(prefix='.layouts-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as out:json.dump(dict(version=1,layouts=self.layouts),out);out.flush();os.fsync(out.fileno())
            os.replace(name,self.path)
        finally:
            try:os.unlink(name)
            except FileNotFoundError:pass

class Arrangements(QObject):
    changed=Signal();notice=Signal(str);saved=Signal(str)
    def __init__(self,bridge,parent=None):
        super().__init__(parent);self.bridge=bridge;self.engine=ArrangementEngine(bridge.windowActions,bridge.preferences.path.with_name('layouts.json')) if bridge.windowActions else None;self._busy=False;self._preview={};self._resume=None
        if self.engine:self.engine.sync=lambda ident:bridge.xwaylandControls.restore_state(ident) if getattr(bridge,'xwaylandControls',None) else None
        if hasattr(bridge,'windowsChanged'):bridge.windowsChanged.connect(self.reconcilePreview)
    available=Property(bool,lambda s:s.engine is not None,constant=True)
    busy=Property(bool,lambda s:s._busy,notify=changed)
    undoLabel=Property(str,lambda s:s.engine.history[-1]['label'] if s.engine and s.engine.history else '',notify=changed)
    layouts=Property('QVariantList',lambda s:layout_cards(s.engine.layouts,s.bridge._apps) if s.engine else [],notify=changed)
    preview=Property('QVariantMap',lambda s:s._preview,notify=changed)
    checkpoints=Property('QVariantList',lambda s:[dict(id=row['id'],label=row['label'],count=len(row['rows']))
                         for row in reversed(s.engine.history)] if s.engine else [],notify=changed)
    @Slot(str,result='QVariantMap')
    def checkpointPreview(self,ident):
        if not self.engine:return {}
        entry=next((row for row in self.engine.history if row['id']==ident),None)
        return checkpoint_preview(entry,self.bridge._windows) if entry else {}
    @Slot(str)
    def restoreCheckpoint(self,ident):
        self.submit(lambda:self.engine.restore_checkpoint(ident),
                    lambda result:self.notice.emit(f"Restored {result['applied']} windows"+
                    (f"; {result['skipped']} unavailable" if result['skipped'] else '')))
    def submit(self,work,done=None):
        if not self.engine or self._busy:return
        self._busy=True;self.changed.emit()
        def finished(value):
            if done:done(value)
        def settled():self._busy=False;self.changed.emit()
        self.bridge.windowTask('__arrangement__','arrangement',work,finished,settled)
    @Slot()
    def undo(self):self.submit(self.engine.undo if self.engine else lambda:None,lambda result:self.notice.emit(f"Restored {result['applied']} windows"+(f"; {result['skipped']} closed windows skipped" if result['skipped'] else '')))
    @Slot(str)
    @Slot(str,str)
    def save(self,name,folder=""):
        identities={str(w['id']):a['id'] for a in self.bridge._dockApps for w in a['windows'] if any(app['id']==a['id'] for app in self.bridge._apps)}
        def done(count):
            self.notice.emit(f'Saved {count} application positions');self.saved.emit(name)
        self.submit(lambda:self.engine.save(name,identities,folder),done)
    @Slot(str)
    def remove(self,ident):self.submit(lambda:self.engine.remove(ident),lambda _:self.clearPreview())
    def live_windows(self):
        result=[]
        for w in self.bridge._windows:
            app=next((a for a in self.bridge._dockApps if any(str(item['id'])==str(w['id']) for item in a['windows'])),None)
            if w.get('native') and (not valid_rect(w.get('rect')) or min(w['rect']['width'],w['rect']['height'])<=1):continue
            result.append(dict(w,appId=app['id'] if app else ''))
        return result
    @Slot(str)
    def openPreview(self,ident):
        if not self.engine or self._busy:return
        if self._resume and self._resume!=ident:self._resume=None
        try:self._preview=self.engine.preview(ident,self.live_windows(),self.bridge._apps)
        except ValueError as error:self.notice.emit(str(error));return
        self.changed.emit()
    @Slot(str)
    def resumeSaved(self, ident):
        self.openPreview(ident)
        if self._preview.get('id') == ident:
            self.resume()
    @Slot()
    def refreshPreview(self):
        if self._preview:self.openPreview(self._preview['id'])
    @Slot()
    def reconcilePreview(self):
        if not self._preview or self._busy:return
        previous=self._preview
        try:current=self.engine.preview(previous['id'],self.live_windows(),self.bridge._apps)
        except ValueError:return self.clearPreview()
        used=set()
        for row,old in zip(current['rows'],previous['rows']):
            selected=old['selected']
            if selected and selected not in used and any(c['id']==selected for c in row['candidates']):
                row['selected']=selected
                used.add(selected)
            else:
                row['selected']=''
        for row in current['rows']:
            if row['selected']:continue
            candidates=[candidate for candidate in row['candidates'] if candidate['id'] not in used]
            if len(candidates)==1:
                row['selected']=candidates[0]['id']
                used.add(row['selected'])
        if current!=previous:self._preview=current;self.changed.emit()
        self.finishResume()
    @Slot()
    def resume(self):
        if self._busy or self._resume or not self._preview:return
        rows=self._preview['rows']
        if any(not row['selected'] and (row['candidates'] or not row['installed']) for row in rows):
            return self.notice.emit('Choose open windows and install missing apps before resuming')
        missing=[row['app'] for row in rows if not row['selected']]
        if not missing:return self.apply(open_folder=True)
        self._resume=self._preview['id']
        pending=object()
        self._resumeToken=pending
        self._resumeApps=set(missing)
        QTimer.singleShot(120000,lambda:self.resumeTimedOut(pending))
        self._resumeQueue=missing
        self.launchNextForResume(pending)
    def launchNextForResume(self,pending):
        if not self._resume or self._resumeToken is not pending:return
        if self._resumeQueue:
            app=self._resumeQueue.pop(0)
            self.bridge.launchForLayout(app,lambda:QTimer.singleShot(0,lambda:self.launchNextForResume(pending)),allow_new=True)
        else:
            self.finishResume()
            QTimer.singleShot(15000,lambda:self.resumeTimedOut(pending))
    def overridesPlacement(self,window):
        if not self._resume:return False
        from desktop import match_application
        app=match_application(window,self.bridge._apps)
        return bool(app and app['id'] in self._resumeApps)
    def finishResume(self):
        if self._resume!=self._preview.get('id') or not self._resume:return
        rows=self._preview['rows']
        if not self._resumeQueue and all(row['selected'] for row in rows) and len({row['selected'] for row in rows})==len(rows):
            self._resume=None
            self.apply(open_folder=True)
    def resumeTimedOut(self,pending):
        if self._resume and self._resumeToken is pending:
            self._resume=None
            self.notice.emit('Some windows did not open. Open another window in the app, then select it in the layout.')
    @Slot(int,str)
    def choose(self,index,ident):
        if self._busy or not 0<=index<len(self._preview.get('rows',[])):return
        row=self._preview['rows'][index]
        if ident and not any(c['id']==ident for c in row['candidates']):return
        row['selected']=ident;self.changed.emit();self.finishResume()
    @Slot()
    def clearPreview(self):self._resume=None;self._preview={};self.changed.emit()
    @Slot()
    def apply(self, open_folder=False):
        preview=copy.deepcopy(self._preview)
        def done(result):
            self.notice.emit(f"Arranged {result['applied']} windows — Undo is available")
            self.clearPreview()
            folder=preview.get('folder')
            if open_folder and result['applied'] and preview['rows']:
                self.bridge.switchDesktop(preview['rows'][0]['workspace']-1)
            if open_folder and folder:
                if Path(folder).is_dir():
                    self.bridge.launchApplication('mellipi-files.desktop',keep_open=True,file_uri=Path(folder).as_uri())
                else:
                    self.notice.emit('The saved project folder is unavailable')
        if preview:self.submit(lambda:self.engine.apply(preview),done)

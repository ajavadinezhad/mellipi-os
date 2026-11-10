"""Bounded, on-demand Sway arrangement history and private reusable layouts.

No titles, contents, screenshots or background sampling are saved. Runtime undo
uses live client identity; saved layouts require explicit matching before apply.
"""
import copy,json,math,os,stat,tempfile,threading,uuid,time,sys
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot
from window_actions import find_window,valid_rect

def client_key(node):
    return (node.get('pid',0),node.get('app_id') or (node.get('window_properties') or {}).get('class',''),node.get('window',0))

def bounded_rect(rect,area):
    w=min(rect['width'],area['width']);h=min(rect['height'],area['height'])
    return dict(x=max(area['x'],min(rect['x'],area['x']+area['width']-w)),y=max(area['y'],min(rect['y'],area['y']+area['height']-h)),width=w,height=h)

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
                        rows.append(dict(id=ident,key=client_key(node),rect=dict(rect),area=dict(area),desktop=space['num'],output=output,floating=bool(target['_floating']),fullscreen=bool(node.get('fullscreen_mode')),focused=bool(node.get('focused')),saved=copy.deepcopy(self.actions.saved.get(ident)),snapped=copy.deepcopy(self.actions.snapped.get(ident))))
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
                    if before:self.history=(self.history+[(label,before)])[-10:]
                    # Do not replace the original operation error with an IPC
                    # failure while checking its result.
                    if not action_failed:raise
                else:
                    if before and before!=after:self.history=(self.history+[(label,before)])[-10:]
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
            if undo and row['area']==area:rect=bounded_rect(row['rect'],area)
            else:
                prior=row['area'];r=row['rect']
                rect=bounded_rect(dict(x=area['x']+round((r['x']-prior['x'])/prior['width']*area['width']),y=area['y']+round((r['y']-prior['y'])/prior['height']*area['height']),width=max(1,round(r['width']/prior['width']*area['width'])),height=max(1,round(r['height']/prior['height']*area['height']))),area)
            self.actions._resize(ident,rect)
            # Sway versions differ on whether floating resize includes the CSD
            # frame. Measure one configure reply rather than accumulating borders.
            time.sleep(.04)
            measured=find_window(self.actions.request(4),ident)
            if measured:
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
            label,rows=self.history[-1]
            result=self.restore_rows(rows,True);self.history.pop();return result
    def save(self,name,identities):
        name=name.strip()
        if not name or len(name)>48 or any(ord(c)<32 for c in name):raise ValueError('Use a layout name of 1–48 characters')
        with self.lock,self.actions.lock:
            rows=self.capture();saved=[]
            for row in rows:
                app=identities.get(str(row['id']))
                if not app:continue
                saved.append(dict(app=app,klass=str(row['key'][1])[:256],rect=row['rect'],area=row['area'],desktop=row['desktop'],floating=row['floating'],fullscreen=row['fullscreen']))
            if not saved:raise ValueError('No recognized application windows to save')
            if len(saved)>24:raise ValueError('Save layouts with at most 24 application windows')
            if len(self.layouts)>=12:raise ValueError('Remove a saved layout first (limit 12)')
            self.layouts.append(dict(id=uuid.uuid4().hex,name=name,windows=saved))
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
            rows.append(dict(index=index,app=row['app'],workspace=row['desktop'],name=app['name'] if app else row['app'],candidates=candidates,selected=selected,installed=bool(app),status='Reuse open window' if selected else 'Choose a window' if candidates else 'Open application first' if app else 'Application is not installed'))
        return dict(id=ident,name=saved['name'],rows=rows)
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
            rows.append(dict(current,rect=layout['rect'],area=layout['area'],desktop=layout['desktop'],floating=True,fullscreen=layout['fullscreen'],focused=False))
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
                if not isinstance(layout.get('windows'),list) or not 1<=len(layout['windows'])<=24:raise ValueError('Invalid saved layout windows')
                for row in layout['windows']:
                    if not isinstance(row,dict) or not valid_rect(row.get('rect')) or not valid_rect(row.get('area')) or type(row.get('desktop')) is not int or not 1<=row['desktop']<=99 or not all(isinstance(row.get(k),str) and 0<len(row[k])<=256 for k in ('app','klass')) or type(row.get('fullscreen')) is not bool or type(row.get('floating')) is not bool:raise ValueError('Invalid saved layout window')
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
        super().__init__(parent);self.bridge=bridge;self.engine=ArrangementEngine(bridge.windowActions,bridge.preferences.path.with_name('layouts.json')) if bridge.windowActions else None;self._busy=False;self._preview={}
        if self.engine:self.engine.sync=lambda ident:bridge.xwaylandControls.restore_state(ident) if getattr(bridge,'xwaylandControls',None) else None
        if hasattr(bridge,'windowsChanged'):bridge.windowsChanged.connect(self.reconcilePreview)
    available=Property(bool,lambda s:s.engine is not None,constant=True)
    busy=Property(bool,lambda s:s._busy,notify=changed)
    undoLabel=Property(str,lambda s:s.engine.history[-1][0] if s.engine and s.engine.history else '',notify=changed)
    layouts=Property('QVariantList',lambda s:[dict(id=r['id'],name=r['name'],count=len(r['windows'])) for r in s.engine.layouts] if s.engine else [],notify=changed)
    preview=Property('QVariantMap',lambda s:s._preview,notify=changed)
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
    def save(self,name):
        identities={str(w['id']):a['id'] for a in self.bridge._dockApps for w in a['windows'] if any(app['id']==a['id'] for app in self.bridge._apps)}
        def done(count):
            self.notice.emit(f'Saved {count} application positions');self.saved.emit(name)
        self.submit(lambda:self.engine.save(name,identities),done)
    @Slot(str)
    def remove(self,ident):self.submit(lambda:self.engine.remove(ident),lambda _:self.clearPreview())
    def live_windows(self):
        result=[]
        for w in self.bridge._windows:
            app=next((a for a in self.bridge._dockApps if any(str(item['id'])==str(w['id']) for item in a['windows'])),None)
            result.append(dict(w,appId=app['id'] if app else ''))
        return result
    @Slot(str)
    def openPreview(self,ident):
        if not self.engine or self._busy:return
        try:self._preview=self.engine.preview(ident,self.live_windows(),self.bridge._apps)
        except ValueError as error:self.notice.emit(str(error));return
        self.changed.emit()
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
            if selected and selected not in used and any(c['id']==selected for c in row['candidates']):row['selected']=selected
            if row['selected'] in used:row['selected']=''
            if row['selected']:used.add(row['selected'])
        if current!=previous:self._preview=current;self.changed.emit()
    @Slot(int,str)
    def choose(self,index,ident):
        if self._busy or not 0<=index<len(self._preview.get('rows',[])):return
        row=self._preview['rows'][index]
        if ident and not any(c['id']==ident for c in row['candidates']):return
        row['selected']=ident;self.changed.emit()
    @Slot()
    def clearPreview(self):self._preview={};self.changed.emit()
    @Slot()
    def apply(self):
        preview=copy.deepcopy(self._preview)
        if preview:self.submit(lambda:self.engine.apply(preview),lambda result:(self.notice.emit(f"Arranged {result['applied']} windows — Undo is available"),self.clearPreview()))

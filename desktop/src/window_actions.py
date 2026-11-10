"""On-demand stacking window actions using Sway IPC, with bounded restore state."""
import hashlib,json,os,stat as stat_module,tempfile,threading,time
from pathlib import Path

def valid_rect(rect):
    if not isinstance(rect,dict):return False
    values=[rect.get(k) for k in ('x','y','width','height')]
    return all(type(v) is int and abs(v)<=2_000_000 for v in values) and min(values[2:])>0

def session_state_path():
    """Keep restore geometry in this user's private compositor-session runtime."""
    socket=os.environ.get('SWAYSOCK','');runtime=Path(os.environ.get('XDG_RUNTIME_DIR',''))
    if not socket or not runtime.is_absolute() or not runtime.is_dir():return None
    directory=runtime/'orbit-window-state'
    try:
        if directory.is_symlink():return None
        directory.mkdir(mode=0o700,exist_ok=True)
        stat=directory.stat()
        if stat.st_uid!=os.getuid() or stat.st_mode&0o077:return None
        return directory/(hashlib.sha256(socket.encode()).hexdigest()[:20]+'.json')
    except OSError:return None

def find_window(tree,ident):
    def walk(node,workspace=None,floating=None):
        if node.get('type')=='workspace':workspace=node
        if node.get('type')=='floating_con':floating=node
        if node.get('id')==ident and (node.get('app_id') or node.get('window')):
            frame=floating or node;rect=dict(frame['rect'])
            if frame.get('window') or frame.get('app_id'):
                height=frame.get('deco_rect',{}).get('height',0)
                rect['y']-=height;rect['height']+=height
            return {**node,'_outer_rect':rect,'_floating':floating is not None},workspace
        for child in node.get('nodes',[])+node.get('floating_nodes',[]):
            found=walk(child,workspace,floating)
            if found:return found
    return walk(tree)

def obscured_tiled_window(node,workspace):
    """Floating views render above tiling even after the tiled view gets focus."""
    if not workspace or node.get('_floating'):return False
    rect=node.get('_outer_rect',{})
    if not valid_rect(rect):return False
    floating=workspace.get('floating_nodes',[]);overlap=False
    for frame in floating:
        pending=[frame];contains_target=False;has_view=False
        while pending:
            item=pending.pop()
            if item.get('id')==node['id']:contains_target=True
            if item.get('app_id') or item.get('window'):has_view=True
            pending.extend(item.get('nodes',[]));pending.extend(item.get('floating_nodes',[]))
        # Membership also handles compositor versions that omit floating_con.
        if contains_target:return False
        other=frame.get('rect',{})
        if has_view and valid_rect(other) and rect['x']<other['x']+other['width'] and other['x']<rect['x']+rect['width'] and rect['y']<other['y']+other['height'] and other['y']<rect['y']+rect['height']:
            overlap=True
    return overlap

class WindowActions:
    def __init__(self,request=None,command=None,state_path=None):
        default_ipc=request is None and command is None
        if request is None or command is None:
            import sway_events
            request=request or sway_events.request;command=command or sway_events.command
        self.request=request;self.command=command;self.saved={};self.minimized={};self.snapped={};self.lock=threading.RLock();self._maximized=frozenset()
        self.state_path=Path(state_path) if state_path is not None else session_state_path() if default_ipc else None
        self._load()

    def _load(self):
        path=self.state_path
        if path is None:return
        try:
            stat=path.lstat()
            if not path.is_absolute() or not stat_module.S_ISREG(stat.st_mode) or path.is_symlink() or stat.st_uid!=os.getuid() or stat.st_mode&0o077 or stat.st_size>65536:return
            data=json.loads(path.read_text())
            if not isinstance(data,dict) or data.get('version')!=1:return
            def restore_rows(rows):
                if not isinstance(rows,list) or len(rows)>128:raise ValueError('Invalid restore state')
                restored={}
                for row in rows:
                    if not isinstance(row,dict):raise ValueError('Invalid restore row')
                    ident=row.get('id');rect=row.get('rect');floating=row.get('floating')
                    if type(ident) is not int or not 0<ident<2**63 or not valid_rect(rect) or type(floating) is not bool:raise ValueError('Invalid restore geometry')
                    restored[ident]=({k:rect[k] for k in ('x','y','width','height')},floating)
                return restored
            restored=restore_rows(data.get('windows'));minimized=restore_rows(data.get('minimized',[]));snapped=restore_rows(data.get('snapped',[]))
            self.saved=restored;self.minimized=minimized;self.snapped=snapped;self._maximized=frozenset(restored)
        except (OSError,ValueError,TypeError):pass

    def _persist(self):
        path=self.state_path
        if path is None:return
        staged=None
        try:
            parent=path.parent
            if not path.is_absolute() or parent.is_symlink():return
            stat=parent.stat()
            if stat.st_uid!=os.getuid() or stat.st_mode&0o077:return
            rows=[dict(id=ident,rect=rect,floating=floating) for ident,(rect,floating) in self.saved.items()]
            minimized=[dict(id=ident,rect=rect,floating=floating) for ident,(rect,floating) in self.minimized.items()]
            snapped=[dict(id=ident,rect=rect,floating=floating) for ident,(rect,floating) in self.snapped.items()]
            fd,staged=tempfile.mkstemp(prefix='.restore-',dir=parent)
            with os.fdopen(fd,'w') as stream:json.dump(dict(version=1,windows=rows,minimized=minimized,snapped=snapped),stream,separators=(',',':'))
            os.replace(staged,path);staged=None
        except (OSError,ValueError,TypeError):pass
        finally:
            if staged is not None:
                try:os.unlink(staged)
                except OSError:pass

    def is_maximized(self,ident):
        """Read the last committed state without waiting for compositor IPC."""
        return ident in self._maximized

    def _target(self,ident):
        if type(ident) is not int or ident<=0:raise ValueError('Invalid window identifier')
        target=find_window(self.request(4),ident)
        if not target:raise ValueError('Window has closed')
        return target

    def prune(self,tree):
        with self.lock:
            changed=False
            for ident in list(self.saved):
                if not find_window(tree,ident):self.saved.pop(ident,None);changed=True
            for ident in list(self.minimized):
                if not find_window(tree,ident):self.minimized.pop(ident,None);changed=True
            for ident in list(self.snapped):
                if not find_window(tree,ident):self.snapped.pop(ident,None);changed=True
            self._maximized=frozenset(self.saved)
            if changed:self._persist()

    def minimize(self,ident):
        with self.lock:
            node,workspace=self._target(ident)
            if workspace and workspace.get('name')=='__i3_scratch':return
            saved=(dict(node['_outer_rect']),node['_floating'] or node.get('floating') in ('auto_on','user_on'))
            self.command(f'[con_id={ident}] move scratchpad')
            self.minimized.pop(ident,None)
            if valid_rect(saved[0]):
                if len(self.minimized)>=128:self.minimized.pop(next(iter(self.minimized)))
                self.minimized[ident]=saved
            self._persist()

    def restore(self,ident):
        with self.lock:
            node,workspace=self._target(ident)
            restored_rect=None
            if workspace and workspace.get('name')=='__i3_scratch':
                self.command(f'[con_id={ident}] scratchpad show; [con_id={ident}] move to workspace current')
                saved=self.minimized.get(ident)
                if saved:
                    rect,floating=saved;self._resize(ident,rect)
                    if not floating:
                        restored_rect=dict(rect)
                        self.command(f'[con_id={ident}] floating disable')
                node,workspace=self._target(ident)
            if obscured_tiled_window(node,workspace):
                # Orbit is a stacking desktop. Focus alone cannot bring a
                # tiled app through a floating maximized app; preserve its
                # exact bounds while putting it in the same stacking layer.
                # A just-restored tiling layout may still report the previous
                # floating size until its configure commits. Its recorded
                # pre-minimize bounds are authoritative during this promotion.
                self._resize(ident,restored_rect or node['_outer_rect'])
            self.command(f'[con_id={ident}] focus')
            if ident in self.minimized:self.minimized.pop(ident,None);self._persist()

    def maximize(self,ident,desired=None,prepare=None):
        with self.lock:
            node,workspace=self._target(ident)
            if workspace and workspace.get('name')=='__i3_scratch':
                self.restore(ident);node,workspace=self._target(ident)
            desired=(ident not in self.saved) if desired is None else bool(desired)
            if desired and ident in self.saved:return True
            if not desired:
                saved=self.saved.get(ident)
                if saved:
                    rect,floating=saved
                    if prepare:prepare(False)
                    try:
                        self._resize(ident,rect)
                        if not floating:self.command(f'[con_id={ident}] floating disable')
                    except Exception:
                        if prepare:prepare(True)
                        raise
                    self.saved.pop(ident,None)
                    self._maximized=frozenset(self.saved)
                    self._persist()
                return False
            if not workspace or workspace.get('num',-1)<1:raise ValueError('Window has no visible workspace')
            self.prune(self.request(4))
            if len(self.saved)>=128:raise ValueError('Too many maximized windows')
            rect=dict(node['_outer_rect']);floating=node['_floating'] or node.get('floating') in ('auto_on','user_on')
            if prepare:prepare(True)
            try:self._resize(ident,workspace['rect'])
            except Exception:
                if prepare:prepare(False)
                raise
            self.saved[ident]=(rect,floating);self._maximized=frozenset(self.saved)
            self._persist()
            return True

    def constrain_workarea(self,ident):
        """Repair a screen-filling float whose title has slipped behind a panel.

        Revalidate on the action worker: snapshots may be stale after a drag.
        Keep ordinary windows, intentional fullscreen and scratchpad untouched.
        """
        with self.lock:
            found=find_window(self.request(4),ident)
            if not found:return False
            node,workspace=found
            if not workspace or workspace.get('num',-1)<1 or not node.get('_floating') or node.get('fullscreen_mode'):return False
            rect=node['_outer_rect'];area=workspace.get('rect',{});title=node.get('deco_rect',{}).get('height',0)
            if not valid_rect(rect) or not valid_rect(area) or title<=0:return False
            border=node.get('current_border_width',1)
            if type(border) is not int or not 0<=border<=8:border=1
            horizontal=max(2,border*2);vertical=title+border*2+4
            reserved_edge=max(96,horizontal)
            clipped=(rect['x']<area['x'] or rect['y']<area['y'] or rect['x']+rect['width']>area['x']+area['width'] or rect['y']+rect['height']>area['y']+area['height'])
            if not clipped:return False
            # A newly reserved left edge can leave an untracked, screen-filling
            # client at the output origin. Do not catch ordinary moved windows.
            if not -reserved_edge<=rect['x']-area['x']<=horizontal:return False
            if not -vertical<=rect['y']-area['y']<=horizontal:return False
            if not -2<=rect['width']-area['width']<=reserved_edge:return False
            # A CSD client may add its frame after the maximize configure. Its
            # extra title/border height is not an ordinary window-size change.
            if not -2<=rect['height']-area['height']<=vertical:return False
            if abs(rect['y']+rect['height']-area['y']-area['height'])>vertical:return False
            dw=max(0,rect['width']-area['width']);dh=max(0,rect['height']-area['height'])
            if dw or dh:
                self._resize(ident,area)
                # One bounded configure readback, only on this exceptional path.
                # Ordinary decorated clients already fit after the normal resize.
                time.sleep(.04)
                updated=find_window(self.request(4),ident)
                if not updated:return True
                actual=updated[0]['_outer_rect']
                if all(abs(actual[k]-area[k])<=1 for k in ('x','y','width','height')):return True
                dw=actual['width']-area['width'];dh=actual['height']-area['height']
                if not (0<=dw<=horizontal and 0<=dh<=vertical):return True
                # Sway can interpret resize dimensions as client dimensions for
                # decorated CSD clients. Subtract the measured extra frame once.
                width=max(1,area['width']-dw);height=max(1,area['height']-dh)
                self.command(f'[con_id={ident}] resize set width {width} px height {height} px; [con_id={ident}] move absolute position {area["x"]} px {area["y"]} px')
            else:self.command(f'[con_id={ident}] move absolute position {area["x"]} px {area["y"]} px')
            return True

    def snap(self,ident,side):
        if side not in ('left','right'):raise ValueError('Invalid snap side')
        with self.lock:
            node,workspace=self._target(ident)
            if not workspace or workspace.get('num',-1)<1 or node.get('fullscreen_mode'):raise ValueError('Window cannot be snapped here')
            prior_max=self.saved.get(ident)
            if prior_max:self.maximize(ident,False);node,workspace=self._target(ident)
            original=prior_max or (dict(node['_outer_rect']),bool(node['_floating']))
            if ident not in self.snapped:
                self.prune(self.request(4))
                if len(self.snapped)>=128:raise ValueError('Too many snapped windows')
            area=workspace['rect'];left=area['width']//2
            rect=dict(x=area['x']+(left if side=='right' else 0),y=area['y'],width=area['width']-left if side=='right' else left,height=area['height'])
            self._resize(ident,rect)
            if ident not in self.snapped:self.snapped[ident]=original
            self._persist()

    def restore_size(self,ident):
        """Restore pre-snap size, or unmaximize using the shared restore state."""
        with self.lock:
            if ident in self.saved:self.maximize(ident,False)
            saved=self.snapped.get(ident)
            if saved:
                self._target(ident);rect,floating=saved;self._resize(ident,rect)
                if not floating:self.command(f'[con_id={ident}] floating disable')
                self.snapped.pop(ident,None);self._persist()

    def reflow_maximized(self):
        """Fit tracked maximized windows after panel/output workarea changes."""
        with self.lock:
            tree=self.request(4)
            for ident in list(self.saved):
                found=find_window(tree,ident)
                if not found:continue
                node,space=found
                if not space or space.get('num',-1)<1 or node.get('fullscreen_mode'):continue
                area=space.get('rect',{})
                if valid_rect(area) and node['_outer_rect']!=area:self._resize(ident,area)

    def _resize(self,ident,rect):
        if not valid_rect(rect):raise ValueError('Invalid window geometry')
        values=[rect[k] for k in ('x','y','width','height')]
        x,y,width,height=values
        self.command(f'[con_id={ident}] floating enable; [con_id={ident}] resize set width {width} px height {height} px; [con_id={ident}] move absolute position {x} px {y} px')

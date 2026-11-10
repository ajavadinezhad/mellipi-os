"""On-demand PNG screenshots; no background captures, thumbnails, or polling."""
import os
import math
import struct
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from qt_compat import QObject, Property, Signal, Slot, QTimer, QImage, QDesktopServices, QUrl

PNG = b'\x89PNG\r\n\x1a\n'
MAX_PNG_BYTES = 100_000_000
MAX_CAPTURE_PIXELS = 16_000_000


def pictures_directory(home=None, config_home=None):
    """Read the literal user-dirs value, expanding HOME only; never eval a shell."""
    home = Path(home or Path.home())
    config_home = Path(config_home or os.environ.get('XDG_CONFIG_HOME', str(home / '.config')))
    try:
        with (config_home / 'user-dirs.dirs').open(encoding='utf-8') as source:
            contents = source.read(65536)
        for line in contents.splitlines():
            match = re.fullmatch(r'\s*XDG_PICTURES_DIR\s*=\s*"((?:[^"\\]|\\.)*)"\s*(?:#.*)?', line)
            if not match:continue
            value = re.sub(r'\\([\\"$`])', r'\1', match[1])
            if value == '$HOME' or value == '${HOME}':value = str(home)
            elif value.startswith('$HOME/'):value = str(home) + value[5:]
            elif value.startswith('${HOME}/'):value = str(home) + value[7:]
            if '$' not in value and '`' not in value and Path(value).is_absolute():return Path(value)
    except (OSError, UnicodeError):
        pass
    return home / 'Pictures'


def validate_dimensions(width, height, pixel_ratio=1):
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:raise ValueError('Invalid screenshot dimensions')
    if not isinstance(pixel_ratio, (int, float)) or not math.isfinite(pixel_ratio) or pixel_ratio <= 0:raise ValueError('Invalid display pixel ratio')
    if math.ceil(width * pixel_ratio) * math.ceil(height * pixel_ratio) > MAX_CAPTURE_PIXELS:raise ValueError('Screenshot exceeds the lightweight limit of 16 million pixels')


def clamp_rect(rect, bounds):
    if len(rect) != 4 or any(type(value) is not int for value in rect):raise ValueError('Invalid screenshot area')
    x, y, width, height = rect
    sx, sy, sw, sh = bounds
    if width <= 0 or height <= 0 or sw <= 0 or sh <= 0:raise ValueError('Choose a non-empty screenshot area')
    left, top = max(x, sx), max(y, sy)
    right, bottom = min(x + width, sx + sw), min(y + height, sy + sh)
    if right <= left or bottom <= top:raise ValueError('Screenshot area is outside the selected display')
    return left, top, right - left, bottom - top


def choose_window(windows, recent, current_desktop=None):
    visible = [window for window in windows if not window.get('minimized') and (current_desktop is None or window.get('desktop', current_desktop) in (-1, current_desktop))]
    by_id = {str(window['id']): window for window in visible}
    active = next((str(window['id']) for window in visible if window.get('active')), None)
    return active or next((str(ident) for ident in recent if str(ident) in by_id), '')


def focus_wayland_window(ident):
    if not re.fullmatch(r'[1-9][0-9]*',str(ident)):raise ValueError('Invalid selected window')
    if os.environ.get('ORBIT_NATIVE_CONTROL'):
        from native_compositor import NativeCompositor
        NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']).request('focus',id=int(ident))
        return
    from sway_events import command
    command(f'[con_id={int(ident)}] focus')


def sway_window_rect(ident):
    if os.environ.get('ORBIT_NATIVE_CONTROL'):
        from native_compositor import NativeCompositor
        client=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']);snapshot=client.snapshot()
        selected=next((row for row in snapshot.get('windows',[]) if str(row.get('id'))==str(ident)),None)
        current=next((row.get('id') for row in snapshot.get('desktops',[]) if row.get('active')),None)
        if not selected or selected.get('minimized') or (current is not None and selected.get('desktop')!=current):
            raise ValueError('The selected window is no longer visible')
        rect=selected.get('rect',selected)
        return tuple(int(rect[key]) for key in ('x','y','width','height'))
    from sway_events import request
    def find(node,workspace=None):
        if node.get('type')=='workspace':workspace=node
        if str(node.get('id'))==str(ident) and (node.get('app_id') or node.get('window')):
            if node.get('visible') is False or (workspace and workspace.get('name')=='__i3_scratch'):raise ValueError('The selected window is no longer visible')
            box=node.get('rect',{})
            return tuple(int(box[key]) for key in ('x','y','width','height'))
        for child in node.get('nodes',[])+node.get('floating_nodes',[]):
            result=find(child,workspace)
            if result:return result
        return None
    rect=find(request(4))
    if rect is None:raise ValueError('The selected window is no longer available')
    return rect


def x11_window_rect(ident):
    from Xlib import X, display
    connection = display.Display()
    try:
        window = connection.create_resource_object('window', int(str(ident), 0))
        root = connection.screen().root
        if window.get_attributes().map_state!=X.IsViewable:raise ValueError('The selected window is no longer visible')
        active=root.get_full_property(connection.intern_atom('_NET_ACTIVE_WINDOW'),X.AnyPropertyType)
        if active is None or not len(active.value) or int(active.value[0])!=int(str(ident),0):raise ValueError('The selected window could not be brought to the front; try again')
        geometry = window.get_geometry()
        position = root.translate_coords(window, 0, 0)
        left = right = top = bottom = 0
        extents = window.get_full_property(connection.intern_atom('_NET_FRAME_EXTENTS'), X.AnyPropertyType)
        if extents is not None and len(extents.value) == 4 and all(0 <= int(value) <= 256 for value in extents.value):left, right, top, bottom = map(int, extents.value)
        return position.x - left, position.y - top, geometry.width + left + right, geometry.height + top + bottom
    finally:
        connection.close()


def save_png(folder, image=None, data=None):
    """Create a collision-free, private file; remove partial files on failure."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if data is not None:
        if not data.startswith(PNG) or len(data) < 24 or data[12:16] != b'IHDR' or len(data) > MAX_PNG_BYTES:raise ValueError('Screenshot tool returned invalid or oversized PNG data')
        validate_dimensions(*struct.unpack('>II', data[16:24]))
    elif image is not None and not image.isNull():validate_dimensions(image.width(), image.height())
    descriptor, filename = tempfile.mkstemp(prefix=datetime.now().strftime('Screenshot %Y-%m-%d %H-%M-%S-'), suffix='.png', dir=folder)
    path = Path(filename)
    try:
        if data is not None:
            with os.fdopen(descriptor, 'wb') as output:output.write(data)
        else:
            os.close(descriptor)
            if image is None or image.isNull() or not image.save(str(path), 'PNG'):raise RuntimeError('Could not save screenshot')
        return str(path)
    except Exception:
        try:os.unlink(path)
        except OSError:pass
        raise


def capture_wayland(folder, screen_name, bounds, kind, rect=None, window_id='', pixel_ratio=1):
    from desktop import application_environment
    validate_dimensions(bounds[2], bounds[3], pixel_ratio)
    if kind == 'window':
        focus_wayland_window(window_id)
        rect = clamp_rect(sway_window_rect(window_id), bounds)
    arguments = ['grim', '-t', 'png']
    if kind == 'screen':
        if not screen_name:raise ValueError('The selected display has no capture identifier')
        arguments += ['-o', screen_name]
    else:
        x, y, width, height = clamp_rect(rect, bounds)
        arguments += ['-g', f'{x},{y} {width}x{height}']
    arguments.append('-')
    result = subprocess.run(arguments, capture_output=True, timeout=10, check=False, env=application_environment())
    if result.returncode:raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip()[:200] or 'Screenshot capture failed')
    return save_png(folder, data=result.stdout)


class ScreenshotController(QObject):
    changed = Signal()
    notice = Signal(str)
    received = Signal(object)

    def __init__(self, app, bridge, enabled=True, parent=None):
        super().__init__(parent)
        self.app, self.bridge, self.enabled = app, bridge, enabled
        self._state = dict(busy=False, selecting=False, lastPath='', lastName='', error='', copyToClipboard=True)
        self.folder = pictures_directory() / 'Screenshots'
        self._pool = None
        self._pending = None
        self._closed = False
        self._job = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.take)
        self.received.connect(self.finished)

    state = Property('QVariantMap', lambda self:{**self._state,'destination':str(self.folder)}, notify=changed)

    def screen(self):
        return self.bridge.currentScreen() if hasattr(self.bridge, 'currentScreen') else self.app.primaryScreen()

    @staticmethod
    def bounds(screen):
        if screen is None:raise ValueError('No display is available for capture')
        geometry = screen.geometry()
        return geometry.x(), geometry.y(), geometry.width(), geometry.height()

    @staticmethod
    def pixel_ratio(screen):
        return float(screen.devicePixelRatio()) if hasattr(screen, 'devicePixelRatio') else 1.0

    def error(self, error, finish=True):
        self._state.update(error=' '.join(str(error).split())[:240])
        if finish:self._state['busy'] = False
        self.changed.emit()
        self.notice.emit(self._state['error'])

    def eligible_windows(self):
        current=next((row['id'] for row in getattr(self.bridge,'_desktops',[]) if row.get('active')),None)
        return [window for window in self.bridge._windows if not window.get('minimized') and (current is None or window.get('desktop',current) in (-1,current))]

    def selected_window(self,ident):
        selected=next((window for window in self.eligible_windows() if str(window['id'])==str(ident)),None)
        if selected is None:raise ValueError('The selected window is no longer available on this workspace')
        return str(selected['id'])

    def begin(self, kind, rect=None, window_id=''):
        if self._closed or not self.enabled or self._state['busy']:return
        try:
            screen = self.screen()
            bounds = self.bounds(screen)
            pixel_ratio = self.pixel_ratio(screen)
            validate_dimensions(bounds[2], bounds[3], pixel_ratio)
            ident=self.selected_window(window_id) if kind=='window' else ''
            self._pending = dict(kind=kind, rect=rect, window_id=ident, bounds=bounds, screen_name=screen.name(), pixel_ratio=pixel_ratio)
        except Exception as error:
            self.error(error)
            return
        self._state.update(busy=True, selecting=False, error='')
        self.bridge.dismiss()
        if kind=='window' and hasattr(self.bridge,'focusWindow'):self.bridge.focusWindow(ident)
        self.changed.emit()
        self.timer.start()

    @Slot()
    def captureScreen(self):self.begin('screen')
    @Slot()
    def captureWindow(self):
        if self._closed or not self.enabled or self._state['busy']:return
        if not self.eligible_windows():self.error('No application window is available on this workspace');return
        self._state.update(selecting=False,error='');self.changed.emit()
        self.bridge.showPanel('window-capture')

    @Slot(str)
    def captureSelectedWindow(self,ident):self.begin('window',window_id=ident)

    def captureActiveWindowForQA(self):
        # Python-only fixture entry point; the user's Window action always opens
        # a picker. This route is disabled outside isolated QA sessions.
        if os.environ.get('ORBIT_QA')!='1':return
        ident=choose_window(self.eligible_windows(),self.bridge._mru)
        if not ident:self.error('No application window is available');return
        self.captureSelectedWindow(ident)

    @Slot()
    def beginArea(self):
        if self._closed or not self.enabled or self._state['busy']:return
        try:
            screen = self.screen()
            bounds = self.bounds(screen)
            validate_dimensions(bounds[2], bounds[3], self.pixel_ratio(screen))
        except Exception as error:self.error(error);return
        self.bridge.dismiss()
        self._state.update(selecting=True, error='')
        self.changed.emit()

    @Slot(int, int, int, int)
    def captureArea(self, x, y, width, height):
        if not self._state['selecting']:return
        try:rect = clamp_rect((x, y, width, height), self.bounds(self.screen()))
        except Exception as error:self.error(error);return
        self.begin('area', rect)

    @Slot()
    def cancelArea(self):
        if self._state['selecting']:
            self._state['selecting'] = False
            self.changed.emit()

    @Slot(bool)
    def setCopy(self, enabled):
        self._state['copyToClipboard'] = bool(enabled)
        self.changed.emit()

    @Slot()
    def take(self):
        if self._closed or not self._pending:return
        request, self._pending = self._pending, None
        try:
            screen = self.screen()
            if self.bounds(screen) != request['bounds'] or screen.name() != request['screen_name'] or self.pixel_ratio(screen) != request['pixel_ratio']:raise ValueError('The selected display changed; try capturing again')
            validate_dimensions(request['bounds'][2], request['bounds'][3], request['pixel_ratio'])
            if request['kind']=='window':self.selected_window(request['window_id'])
            if os.environ.get('SWAYSOCK') or os.environ.get('ORBIT_NATIVE_CONTROL'):
                self.submit(lambda:capture_wayland(self.folder, **request))
                return
            rect = request['rect']
            if request['kind'] == 'window':rect = clamp_rect(x11_window_rect(request['window_id']), request['bounds'])
            image = screen.grabWindow(0).toImage()
            if image.isNull():raise ValueError('The display did not return an image')
            validate_dimensions(image.width(), image.height())
            if rect is not None:
                sx, sy, sw, sh = request['bounds']
                x, y, width, height = rect
                scale_x, scale_y = image.width() / sw, image.height() / sh
                image = image.copy(round((x-sx)*scale_x), round((y-sy)*scale_y), max(1, round(width*scale_x)), max(1, round(height*scale_y)))
            image = image.copy()
            self.submit(lambda:save_png(self.folder, image=image))
        except Exception as error:self.error(error)

    def submit(self, work):
        self._job += 1
        job = self._job
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='orbit-screenshot')
        def run():
            try:
                path=work();result=dict(job=job,path=path)
                if self._state['copyToClipboard'] and (os.environ.get('ORBIT_NATIVE_CONTROL') or os.environ.get('SWAYSOCK')):
                    try:
                        client=None
                        if os.environ.get('ORBIT_NATIVE_CONTROL'):
                            from native_compositor import NativeCompositor
                            client=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL'])
                        if client and client.status().get('capabilities',{}).get('native_png_clipboard'):
                            reply=client.request('clipboard_png',path=str(path))
                            if not reply.get('ok'):raise RuntimeError('Screenshot saved; '+reply.get('error','clipboard copy failed'))
                            result['clipboardCopied']=True
                        else:
                            from screenshot_clipboard import publish_png
                            owner=publish_png(path)
                            if getattr(self,'_clipboardOwner',None):self._clipboardOwner.poll()
                            self._clipboardOwner=owner;result['clipboardCopied']=True
                            if client:result['clipboardWarning']='Copied for X11 apps; native Wayland clipboard support activates after your next Mellipi login'
                    except Exception as error:result['clipboardError']=str(error)
                return result
            except Exception as error:return dict(job=job, error=' '.join(str(error).split())[:240])
        future = self._pool.submit(run)
        def done(future):
            if not self._closed and not future.cancelled():self.received.emit(future.result())
        future.add_done_callback(done)

    @Slot(object)
    def finished(self, result):
        if self._closed or result['job'] != self._job:return
        pool, self._pool = self._pool, None
        if pool:pool.shutdown(wait=False)
        if 'error' in result:
            self.error(result['error'])
            return
        path = result['path']
        self._state.update(busy=False, lastPath=path, lastName=Path(path).name, error='')
        if result.get('clipboardError'):self._state['error']=result['clipboardError']
        elif result.get('clipboardWarning'):self._state['error']=result['clipboardWarning']
        if self._state['copyToClipboard'] and not result.get('clipboardCopied') and not result.get('clipboardError'):
            image = QImage(path)
            if not image.isNull():self.app.clipboard().setImage(image)
            else:self._state['error'] = 'Screenshot saved; clipboard image could not be loaded'
        self.changed.emit()
        self.notice.emit(('Screenshot saved · ' if result.get('clipboardWarning') else 'Screenshot saved; clipboard copy failed · ' if self._state['error'] else 'Screenshot copied and saved · ' if self._state['copyToClipboard'] else 'Screenshot saved · ') + Path(path).name)

    @Slot()
    def openLast(self):
        path = self._state['lastPath']
        if not path or not Path(path).is_file():self.error('No saved screenshot is available', finish=False);return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):self.error('Could not open the screenshot', finish=False)

    @Slot()
    def openFolder(self):
        try:self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:self.error(error, finish=False);return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder))):self.error('Could not open the screenshots folder', finish=False)

    @Slot()
    def close(self):
        self._closed = True
        self.timer.stop()
        self._pending = None
        self._state.update(busy=False, selecting=False)
        pool, self._pool = self._pool, None
        if pool:pool.shutdown(wait=True, cancel_futures=True)

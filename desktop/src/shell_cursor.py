"""Static, cached Xcursor arrows for Orbit-owned desktop windows."""
import struct
from pathlib import Path
from qt_compat import QT5,QImage,QColor
if QT5:
    from PyQt5.QtGui import QCursor,QPixmap
else:
    from PySide6.QtGui import QCursor,QPixmap
_CACHE={}

def read_arrow(name,size=24):
    path=Path('/usr/share/icons')/name/'cursors/left_ptr'
    if path.stat().st_size>4_000_000:raise ValueError('Cursor file exceeds limit')
    data=path.read_bytes()
    if data[:4]!=b'Xcur':raise ValueError('Invalid Xcursor header')
    def word(at):
        if at<0 or at+4>len(data):raise ValueError('Truncated cursor file')
        return struct.unpack_from('<I',data,at)[0]
    header,count=word(4),min(1024,word(12));choices=[]
    for i in range(count):
        at=header+i*12
        if word(at)==0xfffd0002:choices.append((abs(word(at+4)-size),word(at+8)))
    for _,at in sorted(choices):
        width,height,xhot,yhot=(word(at+i) for i in (16,20,24,28));start=at+word(at)
        if not (0<width<=128 and 0<height<=128 and xhot<width and yhot<height):continue
        pixels=data[start:start+width*height*4]
        if len(pixels)!=width*height*4:continue
        image=QImage(pixels,width,height,QImage.Format_ARGB32).copy()
        return image,xhot,yhot
    raise ValueError('No usable cursor image')

def arrow(mode,accent=None):
    from application_theme import cursor_name
    name=cursor_name(mode);key=(name,accent)
    if key not in _CACHE:
        image,x,y=read_arrow(name)
        color=QColor(accent or '')
        if accent and color.isValid():
            light=mode=='light'
            for iy in range(image.height()):
                for ix in range(image.width()):
                    pixel=image.pixelColor(ix,iy);gray=(pixel.red()+pixel.green()+pixel.blue())/3
                    # Preserve the contrasting outline and antialiased edges.
                    if pixel.alpha()>220 and ((light and gray<85) or (not light and gray>180)):
                        ratio=.40 if light else .45 if (color.red()+color.green()+color.blue())/3<96 else .76;base=0 if light else 255
                        image.setPixelColor(ix,iy,QColor(round(color.red()*ratio+base*(1-ratio)),round(color.green()*ratio+base*(1-ratio)),round(color.blue()*ratio+base*(1-ratio)),pixel.alpha()))
        if len(_CACHE)>=12:_CACHE.pop(next(iter(_CACHE)))
        _CACHE[key]=QCursor(QPixmap.fromImage(image),x,y)
    return _CACHE[key]

from qt_compat import QObject,QTimer,QEvent,Qt,QApplication
class CursorController(QObject):
    def __init__(self,app):
        super().__init__(app);self.app=app;self.mode='dark';self.accent=None;self.current=None;self.owned=False;self.pending=False;self.appliedMode=None
    def release(self):
        if self.owned:self.app.restoreOverrideCursor();self.owned=False;self.appliedMode=None
    def refresh(self):
        self.pending=False
        if self.current is None:return self.release()
        try:shape=self.current.cursor().shape()
        except RuntimeError:self.current=None;return self.release()
        if shape not in (Qt.ArrowCursor,Qt.BitmapCursor):return self.release()
        if not self.owned:
            if self.app.overrideCursor() is not None:return
            self.app.setOverrideCursor(arrow(self.mode,self.accent));self.owned=True;self.appliedMode=(self.mode,self.accent)
        elif self.appliedMode!=(self.mode,self.accent):self.app.changeOverrideCursor(arrow(self.mode,self.accent));self.appliedMode=(self.mode,self.accent)
    def eventFilter(self,window,event):
        kind=event.type()
        if kind in (QEvent.Enter,QEvent.MouseMove,QEvent.HoverMove,QEvent.MouseButtonRelease):
            self.current=window
            if not self.pending:self.pending=True;QTimer.singleShot(0,self.refresh)
        elif kind in (QEvent.Leave,QEvent.Hide,QEvent.Close):
            if self.current is window:self.current=None;self.release()
        return False

def apply(windows,mode,accent=None):
    app=QApplication.instance()
    controller=getattr(app,'_orbitCursorController',None)
    if controller is None:controller=CursorController(app);app._orbitCursorController=controller
    controller.mode=mode;controller.accent=accent
    for window in windows:
        if window.objectName() in ('desktopSurface','secondaryDesktopSurface','topbarSurface','secondaryTopbarSurface','overlaySurface','contextSurface','noticeSurface','settingsApplicationWindow'):
            window.installEventFilter(controller)
    if controller.current is not None:controller.refresh()

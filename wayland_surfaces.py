"""KDE LayerShellQt's public Qt5 API, using the distro's matching ABI."""
import ctypes,ctypes.util,os
from pathlib import Path
from panel_policy import SPINE_FOOTER_PANELS,CENTERED_PANELS,panel_edge,overlay_layout,taskbar_overlay_layout
from PyQt5 import sip
ROOT=Path(__file__).resolve().parent
library=ctypes.util.find_library('LayerShellQtInterface') if os.environ.get('ORBIT_WAYLAND_RUNTIME')!='private' else None
lib=ctypes.CDLL(library or str(ROOT/'.wayland-runtime/usr/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.5'))

def fn(name,args,returns=None):
    f=getattr(lib,name);f.argtypes=args;f.restype=returns;return f
get=fn('_ZN12LayerShellQt6Window3getEP7QWindow',[ctypes.c_void_p],ctypes.c_void_p)
anchors=fn('_ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE',[ctypes.c_void_p,ctypes.c_uint])
layer=fn('_ZN12LayerShellQt6Window8setLayerENS0_5LayerE',[ctypes.c_void_p,ctypes.c_int])
zone=fn('_ZN12LayerShellQt6Window16setExclusiveZoneEi',[ctypes.c_void_p,ctypes.c_int])
keyboard=fn('_ZN12LayerShellQt6Window24setKeyboardInteractivityENS0_21KeyboardInteractivityE',[ctypes.c_void_p,ctypes.c_int])
output=fn('_ZN12LayerShellQt6Window16setDesiredOutputEP7QScreen',[ctypes.c_void_p,ctypes.c_void_p])
class Margins(ctypes.Structure):_fields_=[('left',ctypes.c_int),('top',ctypes.c_int),('right',ctypes.c_int),('bottom',ctypes.c_int)]
margins=fn('_ZN12LayerShellQt6Window10setMarginsERK8QMargins',[ctypes.c_void_p,ctypes.POINTER(Margins)])

def configure(window,name,compact,dock_align="center",spine=False,panel_position="left",floating=False,thickness=64):
    name={'secondaryDesktopSurface':'desktopSurface','secondaryTopbarSurface':'topbarSurface','secondaryDockSurface':'dockSurface','secondaryDockReserveSurface':'dockReserveSurface'}.get(name,name)
    surface=get(sip.unwrapinstance(window));output(surface,sip.unwrapinstance(window.screen()))
    if name=='desktopSurface':anchors(surface,15);layer(surface,1);zone(surface,-1);keyboard(surface,1 if window.property('desktopEditing') else 2 if window.property('desktopIconsEnabled') else 0)
    elif name=='topbarSurface':
        edge=panel_edge(panel_position)
        anchors(surface,{'left':7,'right':11,'top':13,'bottom':14}[edge] if spine else 13)
        layer(surface,2);zone(surface,(thickness+(16 if floating else 0)) if spine else 30 if compact else 38);keyboard(surface,0)
        margins(surface,ctypes.byref(Margins(0,0,0,0)))
    elif name=='dockReserveSurface':anchors(surface,2);layer(surface,2);zone(surface,0 if spine else 62 if compact else 76);keyboard(surface,0)
    elif name=='dockSurface':
        side={'left':4,'right':8}.get(dock_align,0)
        anchors(surface,2|side);layer(surface,2);zone(surface,-1);keyboard(surface,0)
        margins(surface,ctypes.byref(Margins(12 if side==4 else 0,0,12 if side==8 else 0,10)))
    elif name in ('contextSurface','screenshotSelectionSurface'):anchors(surface,15);layer(surface,3);zone(surface,-1);keyboard(surface,1)
    elif name=='tooltipSurface':anchors(surface,1|4);layer(surface,3);zone(surface,-1);keyboard(surface,0)
    elif name=='overlaySurface':anchors(surface,0);layer(surface,3);zone(surface,-1);keyboard(surface,2)
    else:anchors(surface,1|8);layer(surface,3);zone(surface,-1);keyboard(surface,0);margins(surface,ctypes.byref(Margins(0,42,14,0)))

def position_overlay(window,panel,spine=False,panel_position="left",screen_geometry=None,bar_geometry=None):
    from panel_policy import keyboard_mode
    surface=get(sip.unwrapinstance(window))
    keyboard(surface,keyboard_mode(panel))
    if panel in CENTERED_PANELS:
        anchors(surface,0);margins(surface,ctypes.byref(Margins(0,0,0,0)))
    elif spine:
        layout=taskbar_overlay_layout(panel,screen_geometry,panel_position,bar_geometry) if screen_geometry and bar_geometry else overlay_layout(panel,panel_position)
        anchors(surface,layout['anchors']);margins(surface,ctypes.byref(Margins(*layout['margins'])))
    elif panel in SPINE_FOOTER_PANELS:
        anchors(surface,1|8);margins(surface,ctypes.byref(Margins(0,42,12,0)))
    else:anchors(surface,0);margins(surface,ctypes.byref(Margins(0,0,0,0)))


def position_tooltip(window,x,y):
    surface=get(sip.unwrapinstance(window));margins(surface,ctypes.byref(Margins(int(x),int(y),0,0)))


def position_frame(window,x,y):
    """Place the active server-decoration controls within their selected output."""
    surface=get(sip.unwrapinstance(window))
    margins(surface,ctypes.byref(Margins(max(0,int(x)),max(0,int(y)),0,0)))

"""Static, theme-matched lock wallpaper; generated once per bounded cache key.

Only bundled SVGs are rendered. No screenshot, password handling, blur, animation,
watcher or resident process. Rendering failure must never stop secure locking.
"""
import ctypes,ctypes.util,hashlib,json,math,os,re,stat,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
VERSION=4
MAX_PIXELS=9_000_000
MAX_CACHE_FILES=12

def lock_style(values):
    from theme_catalog import palette,wallpaper_source
    light=values.get('mode')=='light';hc=values.get('highContrast') is True
    chosen=palette(values.get('themePreset','custom'))
    defaults=dict(background='#eef2f6' if light else '#07090c',surface='#ffffff' if light else '#101419',border='#bac8d3' if light else '#38424d',text='#15222d' if light else '#e1e8ed',muted='#526473' if light else '#adb7c4')
    defaults.update({key:chosen[key] for key in defaults if key in chosen})
    defaults.update(accent=values.get('accent','#a9d9c3'),warning='#986411' if light else '#dfc27d',error='#b52b2b' if light else '#e99b91',highContrast=hc,light=light,textScale=max(.85,min(1.5,float(values.get('textScale',1)))))
    if hc:defaults.update(background='#ffffff' if light else '#000000',surface='#ffffff' if light else '#000000',border='#000000' if light else '#ffffff',text='#000000' if light else '#ffffff',muted='#222222' if light else '#eeeeee')
    source=wallpaper_source(values.get('wallpaper','auto'))
    if not source:
        style=values.get('wallpaper','auto');suffix='light' if light else 'black' if values.get('darkLevel')=='black' else 'dark'
        if style=='fold' or style=='auto' and values.get('shellLayout')=='fold':source='wallpaper-spine-'+suffix+'.svg'
        elif style=='orbit' or style=='auto' and values.get('profile')!='economy':source='wallpaper-light.svg' if light else 'wallpaper-black.svg' if values.get('darkLevel')=='black' else 'wallpaper.svg'
    if values.get('wallpaper')=='solid' and not hc:defaults['background']=values.get('backgroundColor',defaults['background'])
    defaults['wallpaper']=source
    return defaults

def output_specs(rows):
    """Convert logical output geometry to swaylock's integer-scale buffers."""
    result=[]
    for row in rows[:8]:
        try:
            if not row.get('active',True):continue
            name=row['name'];rect=row['rect'];scale=max(1,min(4,math.ceil(float(row.get('scale',1)))))
            width=int(rect['width'])*scale;height=int(rect['height'])*scale
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',name) or int(rect['width'])<320 or int(rect['height'])<480 or min(width,height)<240 or max(width,height)>8192 or width*height>MAX_PIXELS:continue
            result.append((name,width,height,scale))
        except (KeyError,ValueError,TypeError,OverflowError):continue
    return result

def _svg_to_png(source,destination,width,height):
    """Use the installed librsvg/Cairo ABI without a Qt app or GI typelib."""
    class Viewport(ctypes.Structure):_fields_=[('x',ctypes.c_double),('y',ctypes.c_double),('width',ctypes.c_double),('height',ctypes.c_double)]
    cairo=ctypes.CDLL(ctypes.util.find_library('cairo') or 'libcairo.so.2')
    rsvg=ctypes.CDLL(ctypes.util.find_library('rsvg-2') or 'librsvg-2.so.2')
    objects=ctypes.CDLL(ctypes.util.find_library('gobject-2.0') or 'libgobject-2.0.so.0')
    cairo.cairo_image_surface_create.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int];cairo.cairo_image_surface_create.restype=ctypes.c_void_p
    cairo.cairo_create.argtypes=[ctypes.c_void_p];cairo.cairo_create.restype=ctypes.c_void_p
    cairo.cairo_destroy.argtypes=[ctypes.c_void_p];cairo.cairo_surface_destroy.argtypes=[ctypes.c_void_p]
    cairo.cairo_surface_write_to_png.argtypes=[ctypes.c_void_p,ctypes.c_char_p];cairo.cairo_surface_write_to_png.restype=ctypes.c_int
    rsvg.rsvg_handle_new_from_file.argtypes=[ctypes.c_char_p,ctypes.c_void_p];rsvg.rsvg_handle_new_from_file.restype=ctypes.c_void_p
    rsvg.rsvg_handle_render_document.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(Viewport),ctypes.c_void_p];rsvg.rsvg_handle_render_document.restype=ctypes.c_int
    objects.g_object_unref.argtypes=[ctypes.c_void_p]
    handle=rsvg.rsvg_handle_new_from_file(os.fsencode(source),None)
    if not handle:raise ValueError('Could not load bundled lock wallpaper')
    surface=cairo.cairo_image_surface_create(0,width,height);context=cairo.cairo_create(surface)
    try:
        if not rsvg.rsvg_handle_render_document(handle,context,ctypes.byref(Viewport(0,0,width,height)),None):raise ValueError('Could not render bundled lock wallpaper')
        if cairo.cairo_surface_write_to_png(surface,os.fsencode(destination)):raise OSError('Could not write lock wallpaper')
    finally:cairo.cairo_destroy(context);cairo.cairo_surface_destroy(surface);objects.g_object_unref(handle)

def render(destination,width,height,scale,style):
    import cairo
    width=int(width);height=int(height)
    if width/max(1,scale)<320 or height/max(1,scale)<480 or width*height>MAX_PIXELS:raise ValueError('Unsupported lock image dimensions')
    surface=cairo.ImageSurface(cairo.FORMAT_RGB24,width,height);context=cairo.Context(surface)
    def color(value,alpha=1):
        context.set_source_rgba(*(int(value[i:i+2],16)/255 for i in (1,3,5)),alpha)
    color(style['background']);context.paint()
    source=ROOT/'native'/style['wallpaper'] if style.get('wallpaper') else None
    if source and source.parent==ROOT/'native' and source.is_file():
        with tempfile.TemporaryDirectory(prefix='orbit-lock-art-') as temp:
            image=Path(temp)/'art.png'
            _svg_to_png(source,image,width,height)
            art=cairo.ImageSurface.create_from_png(str(image));context.set_source_surface(art);context.paint();art.finish()
    surface.write_to_png(str(destination));surface.finish()

def cached_image(directory,width,height,scale,style):
    directory=Path(directory)
    if directory.is_symlink():raise ValueError('Unsafe lock wallpaper cache')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=directory.stat()
    if info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Lock wallpaper cache must be private')
    source=ROOT/'native'/style.get('wallpaper','')
    stamp=source.stat().st_mtime_ns if style.get('wallpaper') and source.is_file() else 0
    key=hashlib.sha256(json.dumps([VERSION,width,height,scale,style,stamp],sort_keys=True).encode()).hexdigest()[:24]
    path=directory/(key+'.png')
    if path.exists() or path.is_symlink():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Unsafe cached lock wallpaper')
        return path
    fd,temp=tempfile.mkstemp(prefix='.render-',suffix='.png',dir=directory);os.close(fd)
    try:render(temp,width,height,scale,style);os.replace(temp,path)
    finally:
        try:os.unlink(temp)
        except FileNotFoundError:pass
    candidates=sorted((p for p in directory.glob('*.png') if p!=path and not p.is_symlink()),key=lambda p:p.stat().st_mtime_ns,reverse=True)
    for old in candidates[MAX_CACHE_FILES-1:]:
        try:old.unlink()
        except FileNotFoundError:pass
    return path

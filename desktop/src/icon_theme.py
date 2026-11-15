"""Choose one available icon theme consistently for the shell and Settings."""
import os
from functools import lru_cache
from pathlib import Path
from qt_compat import QIcon

def choose(paths):
    return next((name for name in ('Mint-Y','Adwaita','Papirus','breeze','hicolor') if any((Path(root)/name).is_dir() for root in paths)),'hicolor')

def configure():
    paths=[str(Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'icons'),'/usr/local/share/icons','/usr/share/icons']
    QIcon.setThemeSearchPaths(paths);QIcon.setThemeName(choose(paths));QIcon.setFallbackThemeName('hicolor')
    artwork_icon.cache_clear(); _folded_icon.cache_clear()


@lru_cache(maxsize=32)
def artwork_icon(name):
    """Use curated, full-color art without mixing in the control glyph palette."""
    from mellipi_icons import APPS
    from project_paths import PROJECT_ROOT
    if name not in APPS:
        return QIcon()
    app_art = PROJECT_ROOT / 'icons' / 'phosphor' / f'{name}.svg'
    if app_art.is_file():
        return QIcon(str(app_art))
    icon = QIcon()
    for side in (16, 22, 32, 48, 64):
        path = PROJECT_ROOT / 'icons' / 'oxygen' / f'{side}x{side}' / f'{name}.png'
        if path.is_file():
            icon.addFile(str(path))
    return icon if not icon.isNull() else QIcon.fromTheme(name)


def fold_artwork(image, accent):
    """Add a small two-face Mellipi fold; leave the supplied art's colors intact."""
    from qt_compat import QColor, QImage, QPainter
    if image.isNull() or not accent.isValid() or image.width() < 16:
        return image
    size=min(image.width(), image.height())
    mark=max(5, round(size*.27))
    face=accent.name()
    shadow=QColor(accent).darker(175).name()
    light=QColor(accent).lighter(138).name()
    fold=QImage.fromData(
        (f'<svg xmlns="http://www.w3.org/2000/svg" width="{mark}" height="{mark}" viewBox="0 0 12 12">'
         '<path d="M1 4 5 1h6v6l-4 4H1z" fill="#10151d" fill-opacity=".9"/>'
         f'<path d="M2 4.5 5.5 2H10v4.5L6.5 10H2z" fill="{face}"/>'
         f'<path d="M2 4.5 6.5 5 10 2H5.5z" fill="{light}"/>'
         f'<path d="M6.5 5 10 2v4.5L6.5 10z" fill="{shadow}"/>'
         '</svg>').encode(), b'SVG')
    result=image.convertToFormat(QImage.Format.Format_ARGB32)
    painter=QPainter(result)
    inset=max(0, round(size*.025))
    painter.drawImage(image.width()-mark-inset,image.height()-mark-inset,fold)
    painter.end()
    return result

@lru_cache(maxsize=128)
def _folded_icon(name, ink, size):
    from qt_compat import QColor, QImage, QSize
    icon=artwork_icon(name)
    if icon.isNull():
        from mellipi_icons import APPS, svg
        if name not in APPS:
            return QImage()
        image=QImage.fromData(svg(name, '#d9e8ff', badge=True, size=size), b'SVG')
    else:
        image=icon.pixmap(QSize(size,size)).toImage()
    return fold_artwork(image,QColor(ink))


def folded_icon(name, ink, size):
    from qt_compat import QImage
    return QImage(_folded_icon(name, ink, size))

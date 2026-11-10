"""Choose one available icon theme consistently for the shell and Settings."""
import os
from pathlib import Path
from qt_compat import QIcon

def choose(paths):
    return next((name for name in ('Mint-Y','Adwaita','Papirus','breeze','hicolor') if any((Path(root)/name).is_dir() for root in paths)),'hicolor')

def configure():
    paths=[str(Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'icons'),'/usr/local/share/icons','/usr/share/icons']
    QIcon.setThemeSearchPaths(paths);QIcon.setThemeName(choose(paths));QIcon.setFallbackThemeName('hicolor')

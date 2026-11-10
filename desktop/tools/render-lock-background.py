"""Render the lightweight fallback wallpaper; live labels belong to the locker."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from lock_background import lock_style,render
style=lock_style(dict(mode='dark',darkLevel='black',shellLayout='fold',wallpaper='auto',accent='#a9d9c3',profile='economy'))
destination=ROOT/'native/lock-background.png'
render(destination,1280,720,1,style)
print(destination)

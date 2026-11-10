"""Small validated, static theme catalog. No assets, watchers, or runtime workers."""
import json,re
from copy import deepcopy
from pathlib import Path
from project_paths import PROJECT_ROOT

THEME_IDS=('midnight','dune','forest','glacier','ember','lavender','porcelain','graphite')
PALETTE_KEYS=('background','surface','raised','hover','border','text','muted','faint')
COLOR=re.compile(r'#[0-9a-fA-F]{6}\Z')

def load_theme(path):
    row=json.loads(Path(path).read_text())
    if not isinstance(row,dict) or row.get('id') not in THEME_IDS or row['id']!=Path(path).stem:raise ValueError('Invalid theme identifier')
    if not isinstance(row.get('name'),str) or not 1<=len(row['name'])<=32 or not isinstance(row.get('description'),str) or len(row['description'])>180:raise ValueError('Invalid theme label')
    if row.get('mode') not in ('light','dark') or row.get('darkLevel') not in ('normal','black'):raise ValueError('Invalid theme mode')
    palette=row.get('palette')
    if not isinstance(palette,dict) or set(palette)!=set(PALETTE_KEYS):raise ValueError('Invalid theme palette')
    if not all(isinstance(v,str) and COLOR.fullmatch(v) for v in (row.get('accent'),row.get('background'),*palette.values())):raise ValueError('Invalid theme color')
    if row['background'].lower()!=palette['background'].lower():raise ValueError('Theme backgrounds disagree')
    return dict(id=row['id'],name=row['name'],description=row['description'],mode=row['mode'],darkLevel=row['darkLevel'],accent=row['accent'].lower(),background=row['background'].lower(),palette={key:palette[key].lower() for key in PALETTE_KEYS},wallpaper='theme-'+row['id'],wallpaperSource='wallpaper-theme-'+row['id']+'.svg')

def _load():
    rows={}
    for key in THEME_IDS:
        try:rows[key]=load_theme(PROJECT_ROOT/'themes'/f'{key}.json')
        except (OSError,ValueError,TypeError,KeyError):continue
    return rows

_CATALOG=_load()
def presets():return [deepcopy(_CATALOG[key]) for key in THEME_IDS if key in _CATALOG]
def theme(ident):
    if ident not in _CATALOG:raise ValueError('Unknown theme')
    return deepcopy(_CATALOG[ident])
def palette(ident):return deepcopy(_CATALOG.get(ident,{}).get('palette',{}))

def wallpaper_source(style):
    """Return only a bundled basename; arbitrary file/URL input is never accepted."""
    for key in THEME_IDS:
        if style=='theme-'+key:return 'wallpaper-theme-'+key+'.svg'
    return ''

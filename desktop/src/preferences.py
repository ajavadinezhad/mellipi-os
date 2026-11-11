"""Validated, atomically persisted appearance and performance preferences."""
import json, os, re, tempfile
from copy import deepcopy
from pathlib import Path
from project_paths import PROJECT_ROOT as ROOT
from theme_catalog import THEME_IDS,theme,palette,wallpaper_source
DEFAULTS={'compact':True,'accent':'#a9d9c3','profile':'economy','mode':'dark','pins':['firefox.desktop','mellipi-files.desktop','mellipi-terminal.desktop'],'workspaceMotion':True,'wallpaper':'auto','backgroundColor':'#18242b','corners':'rounded','dockAlign':'center','clock24':False,'clockDate':True,'reducedMotion':False,'output':'','matchWindows':True,'matchApps':True,'frameStyle':'auto','frameWidth':2,'launcherSort':'frequent','aiEnabled':False,'darkLevel':'normal','desktopIcons':True,'shellLayout':'fold','panelPosition':'left','taskbarLength':'full','taskbarFloating':False,'topbarConnected':False}
PRESETS=[{'name':'Sage','color':'#a9d9c3'},{'name':'Blue','color':'#a8c9ff'},{'name':'Violet','color':'#c8b6ff'},{'name':'Rose','color':'#f3b6c6'},{'name':'Amber','color':'#edcd98'},{'name':'Coral','color':'#ffb59e'}]
LOCK_KEYS=frozenset(('idleLockEnabled','idleLockMinutes','displayOffMinutes','lockBeforeSleep'))
DEFAULTS.update(idleLockEnabled=True,idleLockMinutes=10,displayOffMinutes=0,lockBeforeSleep=True)
DEFAULTS.update(cursorAccent=True,density='compact',textScale=1.0,highContrast=False,themePreset='custom')
THEME_COLOR_KEYS=frozenset(('mode','darkLevel','accent','backgroundColor'))

class Preferences:
    def __init__(self,path=None):
        self.path=Path(path or os.environ.get('ORBIT_SETTINGS_FILE',str(ROOT/'data/settings.json')))
        self.values=deepcopy(DEFAULTS)
        try:
            raw=json.loads(self.path.read_text())
            if isinstance(raw,dict):
                for key,value in raw.items():
                    # Classic was a public layout, not a different session. Keep
                    # every other saved choice while moving it to the taskbar.
                    if key=='shellLayout' and value=='classic':value='fold'
                    try: self.values[key]=self.validate(key,value)
                    except ValueError: pass
                if raw.get('density') not in ('comfortable','compact','extra'):self.values['density']='compact' if self.values['compact'] else 'comfortable'
                self.values['compact']=self.values['density']!='comfortable'
        except (OSError,ValueError): pass
    @staticmethod
    def validate(key,value):
        if key=='density' and value in ('comfortable','compact','extra'):return value
        if key=='themePreset' and value in ('custom',*THEME_IDS):return value
        if key=='highContrast' and type(value) is bool:return value
        if key=='textScale' and type(value) in (int,float) and .85<=value<=1.5:return round(float(value),2)
        if key in ('idleLockEnabled','lockBeforeSleep') and type(value) is bool:return value
        if key=='idleLockMinutes' and type(value) is int and 1<=value<=120:return value
        if key=='displayOffMinutes' and type(value) is int and 0<=value<=120:return value
        if key in ('cursorAccent','taskbarFloating','topbarConnected','compact','workspaceMotion','clock24','clockDate','reducedMotion','matchWindows','matchApps','aiEnabled','desktopIcons') and isinstance(value,bool): return value
        if key=='taskbarLength' and value in ('full','fit'):return value
        if key=='shellLayout' and value=='fold':return value
        if key=='panelPosition' and value in ('left','right','top','bottom'):return value
        if key=='darkLevel' and value in ('normal','black'):return value
        if key=='launcherSort' and value in ('frequent','recent','name'):return value
        if key=='frameStyle' and value in ('auto','normal','pixel'):return value
        if key=='frameWidth' and type(value) is int and 0<=value<=4:return value
        if key=='output' and isinstance(value,str) and len(value)<=256 and not any(ord(c)<32 for c in value):return value
        if key=='wallpaper' and value in ('auto','solid','orbit','dusk','fold',*('theme-'+ident for ident in THEME_IDS)):return value
        if key=='corners' and value in ('square','soft','rounded'):return value
        if key=='dockAlign' and value in ('left','center','right'):return value
        if key=='mode' and value in ('dark','light'):return value
        if key=='pins' and isinstance(value,list) and len(value)<=16 and all(isinstance(i,str) and re.fullmatch(r'[\w.+-]+\.desktop',i) for i in value):return list(dict.fromkeys(value))
        if key=='profile' and value in ('economy','balanced'): return value
        if key in ('accent','backgroundColor') and isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value): return value.lower()
        raise ValueError('Invalid preference')
    def appearance(self):
        return dict(self.values,themePalette=palette(self.values['themePreset']),themeWallpaper=wallpaper_source(self.values['wallpaper']))
    def apply_theme(self,ident):
        row=theme(ident)
        self.update(dict(themePreset=row['id'],mode=row['mode'],darkLevel=row['darkLevel'],accent=row['accent'],backgroundColor=row['background'],wallpaper=row['wallpaper']))
    def set(self,key,value):
        self.update({key:value})
    def reset_appearance(self):
        self.update({k:v for k,v in DEFAULTS.items() if k not in ('pins','profile','output','launcherSort','textScale','highContrast') and k not in LOCK_KEYS})
    def update(self,changes):
        checked={key:self.validate(key,value) for key,value in changes.items()}
        if 'density' in checked:checked['compact']=checked['density']!='comfortable'
        elif 'compact' in checked:checked['density']='compact' if checked['compact'] else 'comfortable'
        if THEME_COLOR_KEYS.intersection(checked) and 'themePreset' not in checked:checked['themePreset']='custom'
        values={**self.values,**checked}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.orbit-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as handle:
                json.dump(values,handle); handle.flush(); os.fsync(handle.fileno())
            os.replace(name,self.path)
        finally:
            if os.path.exists(name): os.unlink(name)
        self.values=values

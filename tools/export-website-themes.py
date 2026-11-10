#!/usr/bin/env python3
"""Export the desktop's validated palettes as static website data."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DESKTOP=ROOT/'desktop'
SOURCE=DESKTOP/'src'

def export(output):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND','software')
    sys.path.insert(0,str(SOURCE))
    from preferences import DEFAULTS
    from theme_catalog import presets,PALETTE_KEYS
    from PyQt5.QtGui import QGuiApplication
    from PyQt5.QtQml import QQmlComponent,QQmlEngine
    from PyQt5.QtCore import QUrl
    app=QGuiApplication.instance() or QGuiApplication([])
    engine=QQmlEngine()
    qml=(DESKTOP/'native/Theme.qml').read_text().replace('pragma Singleton','',1)
    rows=[]
    for ident,label in (('light','Light'),('dark','Dark'),('black','Black')):
        mode='light' if ident=='light' else 'dark'
        appearance=dict(DEFAULTS,mode=mode,darkLevel='black' if ident=='black' else 'normal',themePalette={})
        engine.rootContext().setContextProperty('Orbit',dict(appearance=appearance,themeMode=mode,accentColor=DEFAULTS['accent'],compact=True,economy=True))
        component=QQmlComponent(engine);component.setData(qml.encode(),QUrl.fromLocalFile(str(DESKTOP/'native/Theme.qml')))
        obj=component.create()
        if obj is None:raise RuntimeError('; '.join(error.toString() for error in component.errors()))
        palette={key:obj.property(key).name() for key in PALETTE_KEYS}
        rows.append(dict(id=ident,name=label,mode=mode,accent=DEFAULTS['accent'],palette=palette))
        obj.deleteLater()
    rows.extend({key:row[key] for key in ('id','name','mode','accent','palette')} for row in presets())
    if len(rows)!=11:raise ValueError('Desktop theme catalog is incomplete')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'defaultTheme':'dark','themes':rows},indent=2)+'\n')
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'website/themes.json');args=parser.parse_args()
    rows=export(args.output);print(json.dumps({'output':str(args.output),'themes':[row['name'] for row in rows]}))
if __name__=='__main__':main()

#!/usr/bin/python3 -I
"""One-shot ordinary xdg-shell file chooser; never a shell layer surface."""
import argparse,json,os,sys
from pathlib import Path

MAX_SELECTIONS=128
MAX_OUTPUT=131072

def picker_environment(source):
    # Keep the caller's private profile and session routing, not its panel
    # protocol, plugin injection paths, renderer overrides or provider secrets.
    allowed={'HOME','PATH','USER','LOGNAME','LANG','LANGUAGE','DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS',
             'XDG_RUNTIME_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','XDG_DATA_DIRS','XDG_CONFIG_DIRS','XDG_CURRENT_DESKTOP','XDG_SESSION_TYPE','XDG_SESSION_DESKTOP'}
    env={k:v for k,v in source.items() if k in allowed or k.startswith('LC_')}
    env['ORBIT_QT']=source.get('ORBIT_QT','5')
    if source.get('ORBIT_WAYLAND_RUNTIME')=='system':env['ORBIT_WAYLAND_RUNTIME']='system'
    env['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell'
    if source.get('WAYLAND_DISPLAY'):env['QT_QPA_PLATFORM']='wayland'
    elif source.get('DISPLAY'):env['QT_QPA_PLATFORM']='xcb'
    return env

def validate_selection(value,mode):
    if mode not in ('directory','files') or not isinstance(value,dict) or value.get('status') not in ('ok','cancelled'):raise ValueError('The file chooser returned an invalid response')
    if value['status']=='cancelled':return []
    paths=value.get('paths')
    if not isinstance(paths,list) or not paths or len(paths)>MAX_SELECTIONS or (mode=='directory' and len(paths)!=1):raise ValueError('Choose up to 128 files or one folder')
    if any(not isinstance(p,str) or not p or len(p)>4096 or '\x00' in p or not Path(p).is_absolute() for p in paths):raise ValueError('Choose valid local files or folders')
    if sum(len(p.encode('utf-8')) for p in paths)>65536:raise ValueError('Choose fewer files at once')
    result=[]
    for value in paths:
        path=Path(value)
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Choose the original files or folders instead of symlinks')
        if (mode=='directory' and not path.is_dir()) or (mode=='files' and not path.is_file()):raise ValueError('A selected file or folder is no longer available')
        result.append(str(Path(os.path.normpath(path))))
    return list(dict.fromkeys(result))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('directory','files'),required=True);parser.add_argument('--initial',required=True);args=parser.parse_args()
    os.environ['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell';os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION',None)
    if os.environ.get('ORBIT_QT')=='5':
        from PyQt5.QtWidgets import QApplication,QFileDialog,QDialog
        from PyQt5.QtGui import QIcon
    else:
        from PySide6.QtWidgets import QApplication,QFileDialog,QDialog
        from PySide6.QtGui import QIcon
    app=QApplication([]);app.setApplicationName('Mellipi file picker');app.setDesktopFileName('mellipi-backup-picker');app.setWindowIcon(QIcon.fromTheme('folder'))
    dialog=QFileDialog(None,'Choose a folder' if args.mode=='directory' else 'Choose files to back up',args.initial)
    dialog.setOption(QFileDialog.DontUseNativeDialog,True)
    dialog.setFileMode(QFileDialog.Directory if args.mode=='directory' else QFileDialog.ExistingFiles)
    if args.mode=='directory':dialog.setOption(QFileDialog.ShowDirsOnly,True)
    dialog.resize(760,500)
    value={'status':'cancelled'}
    if dialog.exec()==QDialog.Accepted:
        value={'status':'ok','paths':dialog.selectedFiles()}
        try:value['paths']=validate_selection(value,args.mode)
        except ValueError:value={'status':'error','error':'Choose fewer valid local files, or choose the original folder instead of a symlink.'}
    raw=json.dumps(value,ensure_ascii=False)
    if len(raw.encode('utf-8'))>MAX_OUTPUT:raw=json.dumps({'status':'error','error':'Choose fewer files at once.'})
    print(raw,flush=True)

if __name__=='__main__':main()

"""Select a shell-only Qt5 compatibility library when its host ABI still matches.

Fail closed to the distribution library after Qt updates. This is a startup
check, not a daemon or an accessibility activation policy.
"""
import hashlib,json,os,re
from pathlib import Path
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
SYSTEM_LIBRARIES=tuple(Path('/usr/lib/x86_64-linux-gnu')/('libQt5'+name+'.so.5') for name in ('WaylandClient','Core','Gui'))

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def runtime_directory(root=ROOT,system_libraries=SYSTEM_LIBRARIES):
    root=Path(root);runtime=root/'.qt5-a11y-runtime';binary=runtime/'lib/libQt5WaylandClient.so.5';manifest=runtime/'manifest.json'
    if os.environ.get('ORBIT_QT_A11Y_RUNTIME')=='0':return None
    try:
        if manifest.stat().st_size>65536 or binary.is_symlink() or not binary.is_file():return None
        data=json.loads(manifest.read_text())
        if not isinstance(data,dict):return None
        expected=data.get('system_libraries',{})
        if not isinstance(expected,dict):return None
        if data.get('qt_version')!='5.15.13' or set(expected)!={str(p) for p in system_libraries}:return None
        for path in system_libraries:
            value=expected[str(path)]
            if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value) or digest(path)!=value:return None
        if data.get('binary_sha256')!=digest(binary):return None
    except (OSError,ValueError,TypeError,KeyError):return None
    return binary.parent

def scoped_environment(environment,root=ROOT):
    """Recheck every new Qt process; discard inherited, obsolete module paths."""
    env=dict(environment);prefix=str(Path(root)/'.qt5-a11y-runtime')
    libraries=[value for value in env.get('LD_LIBRARY_PATH','').split(':') if value and value!=prefix and not value.startswith(prefix+os.sep)]
    if env.get('ORBIT_QT')=='5' and env.get('ORBIT_WAYLAND_RUNTIME')=='system' and env.get('ORBIT_QT_A11Y_RUNTIME')!='0':
        directory=runtime_directory(root)
        if directory is not None:libraries.insert(0,str(directory))
    if libraries:env['LD_LIBRARY_PATH']=':'.join(libraries)
    else:env.pop('LD_LIBRARY_PATH',None)
    return env

if __name__=='__main__':
    import sys
    if '--library-path' in sys.argv:print(scoped_environment(os.environ).get('LD_LIBRARY_PATH',''))
    else:
        directory=runtime_directory()
        if directory is not None:print(directory)

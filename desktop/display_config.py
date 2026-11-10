"""Validated Sway output commands and atomic confirmed-display persistence."""
import json,math,os,re,stat,tempfile
from pathlib import Path

SCALES=(.5,.75,1.,1.25,1.5,1.75,2.,2.5,3.)
TRANSFORMS=('normal','90','180','270','flipped','flipped-90','flipped-180','flipped-270')

def mode_name(mode):
    if mode['refresh']==0:return f'{int(mode["width"])}x{int(mode["height"])}'
    return f'{int(mode["width"])}x{int(mode["height"])}@{int(mode["refresh"])/1000:.3f}Hz'

def catalog(raw):
    rows=[]
    for output in raw[:32]:
        name=output.get('name','')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',name) or not output.get('active'):continue
        modes=[]
        for mode in output.get('modes',[])[:256]+[output.get('current_mode') or {}]:
            if not all(type(mode.get(k)) is int and mode[k]>0 for k in ('width','height')) or type(mode.get('refresh')) is not int or mode['refresh']<0:continue
            value=mode_name(mode)
            if not any(m['value']==value for m in modes):modes.append(dict(value=value,label=f'{mode["width"]} × {mode["height"]}'+(f' · {mode["refresh"]/1000:g} Hz' if mode['refresh'] else '')))
        current=output.get('current_mode') or {}
        if not modes or not current:continue
        rect=output.get('rect',{})
        rows.append(dict(name=name,label=output.get('model') or name,modes=modes,mode=mode_name(current),scale=float(output.get('scale',1)),transform=output.get('transform','normal'),x=int(rect.get('x',0)),y=int(rect.get('y',0)),width=int(rect.get('width',0)),height=int(rect.get('height',0))))
    return rows

def validated(rows,name,mode,scale,transform,x,y):
    row=next((r for r in rows if r['name']==name),None)
    if row is None:raise ValueError('Display is no longer connected')
    if mode not in [m['value'] for m in row['modes']]:raise ValueError('Choose a supported display mode')
    if type(scale) not in (int,float) or not math.isfinite(scale) or scale not in SCALES:raise ValueError('Unsupported display scale')
    if transform not in TRANSFORMS:raise ValueError('Unsupported display rotation')
    if any(type(v) is not int or abs(v)>32768 for v in (x,y)):raise ValueError('Display position must be between -32768 and 32768')
    return dict(name=name,mode=mode,scale=float(scale),transform=transform,x=x,y=y)

def command(row):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',row['name']):raise ValueError('Invalid display name')
    if not re.fullmatch(r'\d{1,5}x\d{1,5}(?:@\d{1,4}\.\d{3}Hz)?',row['mode']):raise ValueError('Invalid display mode')
    if row['transform'] not in TRANSFORMS or not isinstance(row['scale'],(int,float)) or not math.isfinite(row['scale']) or not .25<=row['scale']<=4:raise ValueError('Invalid display settings')
    if any(type(row[k]) is not int or abs(row[k])>32768 for k in ('x','y')):raise ValueError('Invalid display position')
    return f'output {json.dumps(row["name"])} mode {row["mode"]} scale {row["scale"]:g} transform {row["transform"]} position {row["x"]} {row["y"]}'

def persist(path,row):
    path=Path(path)
    if not path.is_absolute():raise ValueError('Display settings path must be absolute')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('Refusing a linked display settings file')
    old=''
    if path.exists():
        info=path.stat()
        if info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_size>65536:raise ValueError('Unsafe display settings file')
        old=path.read_text()
    prefixes=(f'output {json.dumps(row["name"])} ',f'output {row["name"]} ')
    lines=[line for line in old.splitlines() if not line.lstrip().startswith(prefixes)]
    if not lines:lines=['# Orbit confirmed display settings']
    text='\n'.join(lines+[command(row)])+'\n'
    if len(text.encode())>65536:raise ValueError('Display settings file is too large')
    descriptor,temporary=tempfile.mkstemp(prefix='.orbit-outputs-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as handle:handle.write(text);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

def persist_native(path,row):
    """Native JSON is separate from Sway's command configuration."""
    command(row) # shared strict value validation, never execute the string
    path=Path(path)
    if not path.is_absolute() or path.is_symlink():raise ValueError('Unsafe native display settings path')
    path.parent.mkdir(parents=True,exist_ok=True);rows={}
    if path.exists():
        info=path.stat()
        if info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_size>65536:raise ValueError('Unsafe native display settings file')
        rows=json.loads(path.read_text())
        if not isinstance(rows,dict) or len(rows)>32:raise ValueError('Invalid native display configuration')
    rows[row['name']]=row
    text=json.dumps(rows,sort_keys=True)+'\n'
    if len(text)>65536:raise ValueError('Native display settings too large')
    descriptor,temporary=tempfile.mkstemp(prefix='.orbit-native-outputs-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as handle:handle.write(text);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

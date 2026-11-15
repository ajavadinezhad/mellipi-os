"""Validated Sway output commands and atomic confirmed-display persistence."""
import json,math,os,re,stat,tempfile
from pathlib import Path

# Common desktop and video sizes, plus standard ultrawide families. Only
# entries also reported by the connector are offered; this never adds modes.
STANDARD_RESOLUTIONS=frozenset((
    (640,480), (800,600), (1024,768), (1152,864), (1280,720), (1280,800),
    (1280,960), (1280,1024), (1360,768), (1366,768), (1400,1050), (1440,900),
    (1600,900), (1600,1200), (1680,1050), (1920,1080), (1920,1200), (1920,1440),
    (2048,1080), (2048,1152), (2048,1536), (2160,1440), (2256,1504),
    (2560,1080), (2560,1440), (2560,1600), (2880,1620), (2880,1800),
    (3000,2000), (3200,1800), (3200,2000), (3440,1440), (3840,1600),
    (3840,2160), (3840,2400), (4096,2160), (4480,2520), (5120,1440),
    (5120,2160), (5120,2880), (6016,3384), (7680,2160), (7680,4320),
))

SCALES=(.5,.75,1.,1.25,1.5,1.75,2.,2.5,3.)
TRANSFORMS=('normal','90','180','270','flipped','flipped-90','flipped-180','flipped-270')

def mode_name(mode):
    if mode['refresh']==0:return f'{int(mode["width"])}x{int(mode["height"])}'
    return f'{int(mode["width"])}x{int(mode["height"])}@{int(mode["refresh"])/1000:.3f}Hz'

def _usable_mode(mode):
    return (isinstance(mode,dict) and
            all(type(mode.get(k)) is int and mode[k]>0 for k in ('width','height')) and
            type(mode.get('refresh')) is int and mode['refresh']>=0)

def catalog(raw):
    rows=[]
    for output in raw[:32]:
        name=output.get('name','')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',name) or not output.get('active'):continue
        supported={}
        current=output.get('current_mode') or {}
        # An output in transition may advertise modes before it has a usable
        # current mode. Wait for the next snapshot rather than losing all rows.
        if not _usable_mode(current):continue
        for mode in output.get('modes',[])[:256]+[current]:
            if not _usable_mode(mode):continue
            width,height,refresh=(mode[key] for key in ('width','height','refresh'))
            supported[width,height,refresh]=dict(
                value=mode_name(mode),
                label=f'{width} × {height}'+(f' · {refresh/1000:g} Hz' if refresh else ''),
                width=width,height=height,standard=(width,height) in STANDARD_RESOLUTIONS,
            )
        modes=[supported[key] for key in sorted(supported,reverse=True)]
        rect=output.get('rect',{})
        rows.append(dict(name=name,label=output.get('model') or name,modes=modes,mode=mode_name(current),scale=float(output.get('scale',1)),transform=output.get('transform','normal'),x=int(rect.get('x',0)),y=int(rect.get('y',0)),width=int(rect.get('width',0)),height=int(rect.get('height',0))))
    return rows

def validated(rows,name,mode,scale,transform,x,y):
    row=next((r for r in rows if r['name']==name),None)
    if row is None:raise ValueError('Display is no longer connected')
    if mode not in [m['value'] for m in row['modes']]:raise ValueError('Choose a supported display mode')
    if type(scale) not in (int,float) or not math.isfinite(scale) or scale not in SCALES:raise ValueError('Unsupported display scale')
    if transform not in TRANSFORMS:raise ValueError('Unsupported display rotation')
    # Settings sends QML Number as a QVariant double over its JSON bridge.
    # Accept whole coordinates on the wire; keep watchdog and persisted values integral.
    for value in (x,y):
        if (type(value) not in (int,float) or not -32768<=value<=32768
                or (type(value) is float and not value.is_integer())):
            raise ValueError('Display position must be a whole number between -32768 and 32768')
    return dict(name=name,mode=mode,scale=float(scale),transform=transform,x=int(x),y=int(y))

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

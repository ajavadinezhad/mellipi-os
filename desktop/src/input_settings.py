"""Explicit, persisted Sway input controls; no input-event or filesystem polling."""
import json,math,os,re,tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot

from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
FALLBACK_LAYOUTS=[('us','English (US)'),('gb','English (UK)'),('de','German'),('fr','French'),('es','Spanish'),('it','Italian'),('pt','Portuguese'),('br','Portuguese (Brazil)'),('ru','Russian'),('ua','Ukrainian'),('pl','Polish'),('tr','Turkish'),('ara','Arabic'),('ir','Persian'),('in','Indian')]
def available_layouts(path=Path('/usr/share/X11/xkb/rules/evdev.xml')):
    """Read installed XKB choices once; no indexer, command or network lookup."""
    fallback=list(FALLBACK_LAYOUTS)
    try:
        import xml.etree.ElementTree as ET
        with Path(path).open('rb') as stream:
            data=stream.read(2_000_001)
        data=data.replace(b'<!DOCTYPE xkbConfigRegistry SYSTEM "xkb.dtd">',b'')
        if len(data)>2_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():return fallback
        root=ET.fromstring(data);rows={}
        for item in root.findall('./layoutList/layout/configItem')[:256]:
            code=item.findtext('name','');label=item.findtext('description','').strip()
            if re.fullmatch(r'[a-zA-Z0-9_-]{1,32}',code) and label and len(label)<=160:
                rows[code]=''.join(c for c in label if c.isprintable())
        if not rows:return fallback
        # Keep established names stable for stored active-layout matching.
        for code,label in fallback:rows[code]=label
        return sorted(rows.items(),key=lambda row:(row[0]!='us',row[1].casefold()))
    except (OSError,ValueError,ET.ParseError):return fallback

LAYOUTS=available_layouts()
DEFAULTS=dict(layout='us',repeatRate=25,repeatDelay=600,pointerSpeed=0.0,naturalScroll=False,tapToClick=False)

def validate(values):
    if not isinstance(values,dict) or set(values)!=set(DEFAULTS):raise ValueError('Invalid input settings')
    result=dict(values)
    if not isinstance(result['layout'],str):raise ValueError('Choose supported keyboard layouts')
    codes=result['layout'].split(',')
    if not 1<=len(codes)<=4 or len(set(codes))!=len(codes) or any(code not in dict(LAYOUTS) for code in codes):raise ValueError('Choose up to four distinct supported keyboard layouts')
    for key,low,high in (('repeatRate',1,100),('repeatDelay',100,2000)):
        if type(result[key]) is not int or not low<=result[key]<=high:raise ValueError('Invalid '+key)
    speed=result['pointerSpeed']
    if type(speed) not in (int,float) or not math.isfinite(speed) or not -1<=speed<=1:raise ValueError('Pointer speed must be between -1 and 1')
    result['pointerSpeed']=round(float(speed),2)
    if any(type(result[k]) is not bool for k in ('naturalScroll','tapToClick')):raise ValueError('Invalid input toggle')
    return result

def device_identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:+-]{1,256}',value):raise ValueError('Unsupported input device identifier')
    return value

def input_lines(values,keys,selector=''):
    v=validate(values);keys=set(keys)
    if not keys<=set(DEFAULTS):raise ValueError('Invalid input fields')
    toggle=lambda value:'enabled' if value else 'disabled'
    prefix=lambda kind:'input '+(json.dumps(device_identifier(selector)) if selector else 'type:'+kind)
    lines={'layout':[f'{prefix("keyboard")} xkb_layout {json.dumps(v["layout"])}'],
        'repeatRate':[f'{prefix("keyboard")} repeat_rate {v["repeatRate"]}'],
        'repeatDelay':[f'{prefix("keyboard")} repeat_delay {v["repeatDelay"]}'],
        'pointerSpeed':[f'{prefix("pointer")} pointer_accel {v["pointerSpeed"]:.2f}'] if selector else [f'input type:pointer pointer_accel {v["pointerSpeed"]:.2f}',f'input type:touchpad pointer_accel {v["pointerSpeed"]:.2f}'],
        'naturalScroll':[f'{prefix("pointer")} natural_scroll {toggle(v["naturalScroll"])}'] if selector else [f'input type:pointer natural_scroll {toggle(v["naturalScroll"])}',f'input type:touchpad natural_scroll {toggle(v["naturalScroll"])}'],
        'tapToClick':[f'{prefix("touchpad")} tap {toggle(v["tapToClick"])}']}
    return [line for key in DEFAULTS if key in keys for line in lines[key]]

def config_text(values,keys=None,overrides=None):
    v=validate(values);keys=set(DEFAULTS) if keys is None else set(keys)
    if not keys<=set(DEFAULTS):raise ValueError('Invalid input fields')
    metadata=dict(values=v,configured=sorted(keys));lines=input_lines(v,keys)
    if overrides:
        if not isinstance(overrides,dict) or len(overrides)>64:raise ValueError('Too many input devices')
        metadata['overrides']={}
        for identifier,profile in sorted(overrides.items()):
            device_identifier(identifier);pv=validate(profile['values']);pk=set(profile['configured'])
            if not pk<=set(DEFAULTS):raise ValueError('Invalid configured device fields')
            if not pk:continue
            metadata['overrides'][identifier]=dict(values=pv,configured=sorted(pk));lines+=input_lines(pv,pk,identifier)
    return '# Orbit input settings — explicit user preferences\n# orbit-settings: '+json.dumps(metadata,sort_keys=True)+'\n'+'\n'.join(lines)+'\n'

def atomic_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('Refusing a symbolic input settings file')
    fd,name=tempfile.mkstemp(prefix='.orbit-input-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:out.write(text);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def device_type(row):
    kind=row.get('type')
    if kind=='pointer' and 'tap' in (row.get('libinput') or {}):return 'touchpad'
    return kind

def read_current(request,identifier='',include_devices=False):
    rows=request(100);current={};layout_name='';devices=[]
    if not isinstance(rows,list):raise ValueError('Invalid input device response')
    for row in rows[:128]:
        if device_type(row) not in ('keyboard','pointer','touchpad'):continue
        try:ident=device_identifier(row.get('identifier'))
        except ValueError:continue
        name=' '.join(str(row.get('name') or ident).split())[:160]
        devices.append(dict(identifier=ident,name=name,type=device_type(row)))
    scoped=[r for r in rows if not identifier or r.get('identifier')==identifier]
    keyboard=next((r for r in scoped if r.get('type')=='keyboard'),None)
    pointer=next((r for r in scoped if device_type(r) in ('pointer','touchpad')),None)
    touchpad=next((r for r in scoped if device_type(r)=='touchpad'),None)
    if keyboard:
        layout_name=keyboard.get('xkb_active_layout_name','');codes=[]
        names=keyboard.get('xkb_layout_names') or []
        if not isinstance(names,list):names=[]
        for label in names[:4]:
            code=next((code for code,name in LAYOUTS if name.lower()==str(label).lower()),None)
            if not code:codes=[];break
            codes.append(code)
        active=next((code for code,label in LAYOUTS if label.lower()==str(layout_name).lower()),None)
        if codes and len(set(codes))==len(codes):current['layout']=','.join(codes)
        elif active:current['layout']=active
        for field,source in (('repeatRate','repeat_rate'),('repeatDelay','repeat_delay')):
            if type(keyboard.get(source)) is int:current[field]=keyboard[source]
    if pointer:
        libinput=pointer.get('libinput') or {}
        if type(libinput.get('accel_speed')) in (int,float):current['pointerSpeed']=libinput['accel_speed']
        if libinput.get('natural_scroll') in ('enabled','disabled'):current['naturalScroll']=libinput['natural_scroll']=='enabled'
    if touchpad:
        tap=(touchpad.get('libinput') or {}).get('tap')
        if tap in ('enabled','disabled'):current['tapToClick']=tap=='enabled'
    clean={}
    for key,value in current.items():
        try:clean[key]=validate(dict(DEFAULTS,**{key:value}))[key]
        except ValueError:pass
    return (clean,layout_name,devices) if include_devices else (clean,layout_name)

class InputSettings(QObject):
    changed=Signal();notice=Signal(str);completed=Signal(object);readCompleted=Signal(object)
    def __init__(self,enabled=True,path=None,request=None,command=None):
        injected_command=command is not None
        super().__init__();self.enabled=bool(enabled and (command is not None or os.environ.get('SWAYSOCK')) and not os.environ.get('ORBIT_NATIVE_CONTROL'));self.path=Path(path or Path(os.environ.get('ORBIT_DATA',str(ROOT/'data')))/'input.conf')
        self.values=dict(DEFAULTS);self.error='';self.busy=False;self.closed=False;self.pool=None;self.configured=set();self._desired_keys=set();self._reading=False;self.layout_name='';self.layout_known=True
        self.selected='';self._devices=[];self.profiles={}
        self.native=None
        if os.environ.get('ORBIT_NATIVE_CONTROL'):
            try:
                from native_compositor import NativeCompositor
                candidate=NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL'])
                if candidate.status().get('control_capabilities',{}).get('input'):self.native=candidate;self.enabled=bool(enabled)
            except (OSError,ValueError,RuntimeError):pass
            if not self.native:self.error='Native keyboard and pointer configuration is not supported by this backend yet' 
        if command is None:
            from sway_events import command as sway_command
            command=sway_command
        self.command=command;self.completed.connect(self._finished)
        if self.native:request=lambda kind:self.native.request('input_get')['inputs']
        if request is None and not injected_command and os.environ.get('SWAYSOCK'):
            from sway_events import request as sway_request
            request=sway_request
        self.request=request;self.readCompleted.connect(self._read_finished)
        try:
            if self.path.is_file() and not self.path.is_symlink() and self.path.stat().st_size<=65536:
                metadata=next((line[len('# orbit-settings: '):] for line in self.path.read_text().splitlines() if line.startswith('# orbit-settings: ')),None)
                if metadata:
                    metadata=json.loads(metadata);self.values=validate(metadata['values']);self.configured=set(metadata['configured'])
                    if not self.configured<=set(DEFAULTS):raise ValueError('Invalid configured input fields')
                    overrides=metadata.get('overrides',{})
                    if not isinstance(overrides,dict) or len(overrides)>64:raise ValueError('Too many device settings')
                    for identifier,profile in overrides.items():
                        device_identifier(identifier);values=validate(profile['values']);keys=set(profile['configured'])
                        if not keys<=set(DEFAULTS):raise ValueError('Invalid configured device fields')
                        self.profiles[identifier]=dict(values=values,configured=keys)
        except (OSError,ValueError,KeyError,TypeError):self.values=dict(DEFAULTS);self.configured=set();self.profiles={}
        self.profiles['']=dict(values=dict(self.values),configured=set(self.configured))
        self._desired=dict(self.values);self._desired_keys=set(self.configured);self.refresh()
    def _device(self):return next((d for d in self._devices if d['identifier']==self.selected),None)
    def _available(self):return self.enabled and (not self.selected or self._device() is not None)
    def _state(self):
        active=next((code for code,label in LAYOUTS if label.lower()==str(self.layout_name).lower()),None)
        device=self._device()
        if not self.selected and 'layout' in self.configured:active=self.values['layout'].split(',')[0]
        return dict(self.values,layout=(active or self.values['layout'].split(',')[0]) if self.layout_known else '',layoutList=self.values['layout'] if self.layout_known or 'layout' in self.configured else '',layoutName=self.layout_name,device=self.selected,deviceType=device['type'] if device else '',available=self._available(),sessionAvailable=self.enabled,busy=self.busy,reading=self._reading,error=self.error)
    state=Property('QVariantMap',_state,notify=changed)
    layouts=Property('QVariantList',lambda self:[dict(value=k,label=v) for k,v in LAYOUTS],constant=True)
    devices=Property('QVariantList',lambda self:[dict(d) for d in self._devices],notify=changed)
    selectedDevice=Property(str,lambda self:self.selected,notify=changed)
    @Slot(str)
    def selectDevice(self,identifier):
        if self.closed:return
        if self.busy:return self.notice.emit('Wait for the current input change to finish')
        if identifier and not any(d['identifier']==identifier for d in self._devices):return self.notice.emit('Input device is no longer connected')
        self.profiles[self.selected]=dict(values=dict(self.values),configured=set(self.configured))
        self.selected=identifier
        profile=self.profiles.setdefault(identifier,dict(values=dict(self.profiles['']['values']),configured=set()))
        self.values=dict(profile['values']);self.configured=set(profile['configured']);self._desired=dict(self.values);self._desired_keys=set(self.configured);self.layout_name='';self.layout_known=True;self.error=''
        self.changed.emit();self.refresh()
    @Slot()
    def resetDevice(self):
        if not self.selected or self.closed:return
        if self.busy or self._reading:return self.notice.emit('Wait for the current input change to finish')
        if not self._available():return self.notice.emit('Input device is no longer connected')
        defaults=self.profiles['']['values'];self._desired=dict(self.values)
        for key in self.configured:self._desired[key]=defaults[key]
        self._desired_keys=set();self._start()
    def _set(self,key,value):
        if self.closed:return
        if self._reading:return self.notice.emit('Input device details are still loading')
        device=self._device()
        if self.selected:
            allowed={'keyboard':{'layout','repeatRate','repeatDelay'},'pointer':{'pointerSpeed','naturalScroll'},'touchpad':{'pointerSpeed','naturalScroll','tapToClick'}}
            if not device or key not in allowed[device['type']]:return self.notice.emit('This setting does not apply to the selected device')
        try:desired=validate(dict(self._desired,**{key:value}))
        except ValueError as error:self.notice.emit(str(error));return
        if not self._available():self.notice.emit('Input controls require a connected device in Orbit Wayland');return
        self._desired=desired;self._desired_keys.add(key)
        if not self.busy:self._start()
    def _start(self):
        desired=dict(self._desired);keys=set(self._desired_keys);previous=dict(self.values);changed_keys={k for k in DEFAULTS if desired[k]!=previous[k]}|(keys-self.configured);scope=self.selected
        self.busy=True;self.error='';self.changed.emit()
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-input')
        profiles={identifier:dict(values=dict(profile['values']),configured=set(profile['configured'])) for identifier,profile in self.profiles.items()}
        profiles[scope]=dict(values=desired,configured=keys)
        def work():
            applied=False
            def send(values):
                if self.native:
                    self.native.request('input_configure',values=values,keys=sorted(changed_keys),device=scope)
                    if not scope:
                        for identifier,profile in profiles.items():
                            inherited=set(profile['configured'])&changed_keys
                            if identifier and inherited and any(d['identifier']==identifier for d in self._devices):self.native.request('input_configure',values=profile['values'],keys=sorted(inherited),device=identifier)
                    return
                lines=input_lines(values,changed_keys,scope)
                if not scope:
                    # Specific device overrides retain precedence over global
                    # defaults, just as in the persisted configuration order.
                    for identifier,profile in profiles.items():
                        if identifier:
                            inherited=set(profile['configured'])&changed_keys
                            lines+=input_lines(profile['values'],inherited,identifier)
                if lines:self.command('; '.join(lines))
            try:
                if self.path.is_symlink():raise ValueError('Refusing a symbolic input settings file')
                applied=True
                if changed_keys:send(desired)
                global_profile=profiles[''];overrides={k:v for k,v in profiles.items() if k}
                atomic_write(self.path,config_text(global_profile['values'],global_profile['configured'],overrides))
                return dict(values=desired,configured=keys,layoutChanged='layout' in changed_keys,scope=scope,profiles=profiles)
            except Exception as error:
                if applied:
                    try:
                        if changed_keys:send(previous)
                    except Exception:pass
                return dict(error=str(error),attempt=desired,attemptKeys=keys,scope=scope)
        self.pool.submit(work).add_done_callback(lambda f:self.completed.emit(f.result()))
    @Slot(object)
    def _finished(self,result):
        self.busy=False
        if self.closed:return
        if 'error' in result:
            self.error=result['error'];self.notice.emit(self.error)
            if self._desired==result.get('attempt') and self._desired_keys==result.get('attemptKeys'):self._desired=dict(self.values);self._desired_keys=set(self.configured)
        elif not result.get('cycle'):
            self.values=result['values'];self.configured=result['configured'];self.profiles=result['profiles']
            if result.get('layoutChanged'):self.layout_known=True;self.layout_name=dict(LAYOUTS)[self.values['layout'].split(',')[0]]
        self.changed.emit()
        if result.get('cycle'):self.refresh()
        elif self._desired!=self.values or self._desired_keys!=self.configured:self._start()
    @Slot(str)
    def setLayout(self,value):self._set('layout',value)
    @Slot(str)
    def setLayoutList(self,value):
        if not isinstance(value,str):return self.notice.emit('Enter layout codes separated by commas')
        self._set('layout',value.replace(' ',''))
    @Slot()
    def nextLayout(self):
        if self.native:
            layouts=self._desired['layout'].split(',')
            if len(layouts)>1:self._set('layout',','.join(layouts[1:]+layouts[:1]))
            return
        if self.closed or self.busy or not self.enabled:return
        self.busy=True;self.changed.emit()
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-input')
        def cycle():
            # A global shortcut must still work when the settings page happens
            # to have a mouse selected. Single-layout keyboards simply stay put.
            try:self.command('input type:keyboard xkb_switch_layout next');return dict(cycle=True)
            except Exception as error:return dict(error=str(error),cycle=True)
        self.pool.submit(cycle).add_done_callback(lambda f:self.completed.emit(f.result()))
    @Slot(int)
    def setRepeatRate(self,value):self._set('repeatRate',value)
    @Slot(int)
    def setRepeatDelay(self,value):self._set('repeatDelay',value)
    @Slot(float)
    def setPointerSpeed(self,value):self._set('pointerSpeed',value)
    @Slot(bool)
    def setNaturalScroll(self,value):self._set('naturalScroll',value)
    @Slot(bool)
    def setTapToClick(self,value):self._set('tapToClick',value)
    @Slot()
    def refresh(self):
        if self.closed or not self.enabled or self.request is None or self._reading or self.busy:return
        self._reading=True;scope=self.selected
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-input')
        def read():
            try:return dict(result=read_current(self.request,scope,True),scope=scope)
            except Exception as error:return dict(error=str(error),scope=scope)
        self.pool.submit(read).add_done_callback(lambda f:self.readCompleted.emit(f.result()))
    @Slot(object)
    def _read_finished(self,result):
        self._reading=False
        if self.closed:return
        if 'result' in result:self._devices=result['result'][2]
        if result.get('scope')!=self.selected:
            self.refresh();return
        if self.busy:return
        if 'result' in result:
            values,label,_=result['result']
            if not self.selected:
                # A device override can differ from the global default. Reading
                # that device must not replace the user's saved global rule.
                for key in self.configured:values.pop(key,None)
            if 'layout' in self.configured and len(self.values['layout'].split(','))>1:values.pop('layout',None)
            self.values.update(values);self._desired=dict(self.values);self.profiles[self.selected]=dict(values=dict(self.values),configured=set(self.configured))
            self.layout_name=label;self.layout_known=not label or any(name.lower()==str(label).lower() for _,name in LAYOUTS)
            self.error='' if self._available() else 'Selected input device is disconnected'
        self.changed.emit()
    def close(self):
        self.closed=True
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=False)

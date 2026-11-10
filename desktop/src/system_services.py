"""Demand-driven system controls with D-Bus change subscriptions and bounded notifications."""
import json,os,re,subprocess,threading,tempfile,time,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot

def run(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    if result.returncode:raise RuntimeError(result.stderr.strip()[:220] or 'System service unavailable')
    return result.stdout

def audio_devices(kind):
    rows=json.loads(run(['pactl','-f','json','list',kind]))
    if not isinstance(rows,list):raise RuntimeError('Invalid audio device catalog')
    return [r for r in rows[:128] if isinstance(r,dict) and isinstance(r.get('name'),str)]

def is_monitor(source):
    return source.get('name','').endswith('.monitor') or source.get('monitor_of_sink') not in (None,'n/a',4294967295,'4294967295')

def audio_volume(device):
    values=[]
    for channel in device.get('volume',{}).values():
        try:values.append(float(str(channel.get('value_percent','0%')).rstrip('%')))
        except (ValueError,TypeError):pass
    return max(0,min(100,round(sum(values)/max(1,len(values)))))

def audio_unplugged(device):
    port=next((p for p in device.get('ports',[]) if p.get('name')==device.get('active_port')),None)
    return bool(port and port.get('availability') in ('not available','no'))

def audio_label(device):
    return (device.get('description') or device['name'])+(' · Unplugged' if audio_unplugged(device) else '')

def audio_cards():
    cards=[]
    for card in audio_devices('cards')[:32]:
        profiles=card.get('profiles',{})
        if isinstance(profiles,dict):profiles=[dict(value,name=name) for name,value in profiles.items() if isinstance(value,dict)]
        if not isinstance(profiles,list):continue
        choices=[]
        for profile in profiles[:64]:
            if not isinstance(profile,dict) or not isinstance(profile.get('name'),str):continue
            available=profile.get('available',True) not in (False,'no','not available')
            choices.append(dict(name=profile['name'],description=str(profile.get('description') or profile['name'])[:200]+(' · Not connected' if not available else ''),available=available,sinks=profile.get('sinks',0),sources=profile.get('sources',0)))
        active=card.get('active_profile','')
        if isinstance(active,dict):active=active.get('name','')
        properties=card.get('properties',{})
        if not isinstance(properties,dict):properties={}
        label=str(card.get('description') or properties.get('device.description') or card['name'])
        nickname=properties.get('device.nick')
        if isinstance(nickname,str) and nickname and nickname not in label:label+=' · '+nickname
        cards.append(dict(name=card['name'],description=label[:200],activeProfile=active if isinstance(active,str) else '',profiles=choices))
    return cards

def set_audio_profile(card_name,profile_name):
    for value in (card_name,profile_name):
        if not isinstance(value,str) or not value or len(value)>512 or value.startswith('-') or any(ord(c)<32 for c in value):raise ValueError('Invalid audio profile')
    card=next((c for c in audio_cards() if c['name']==card_name),None)
    if card is None or not any(p['name']==profile_name for p in card['profiles']):raise ValueError('Audio profile is no longer available')
    before=json.loads(run(['pactl','-f','json','info']))
    # An unavailable jack is still an explicit recovery choice. Never enable a
    # profile from discovery alone, and never move recording streams here.
    run(['pactl','set-card-profile',card_name,profile_name])
    for kind,key,verb in (('sinks','default_sink_name','set-default-sink'),('sources','default_source_name','set-default-source')):
        try:
            devices=audio_devices(kind);name=before.get(key)
            if any(d['name']==name and (kind=='sinks' or not is_monitor(d)) for d in devices):run(['pactl',verb,name])
        except (OSError,RuntimeError,ValueError,subprocess.SubprocessError):pass

def audio_snapshot(include_cards=True):
    info=json.loads(run(['pactl','-f','json','info']));sinks=audio_devices('sinks')
    try:sources=[s for s in audio_devices('sources') if not is_monitor(s)]
    except (RuntimeError,OSError,ValueError,subprocess.SubprocessError):sources=[]
    sink=next((s for s in sinks if s['name']==info.get('default_sink_name')),None)
    source=next((s for s in sources if s['name']==info.get('default_source_name')),None)
    catalog=lambda rows:[dict(name=r['name'],description=audio_label(r)) for r in rows]
    unplugged=bool(sources) and all(audio_unplugged(s) for s in sources)
    state=dict(audioAvailable=bool(sink),volume=audio_volume(sink) if sink else 0,muted=bool(sink.get('mute',False)) if sink else False,audioName=(sink.get('description') or sink['name']) if sink else 'No output device',
        audioOutputs=catalog(sinks),audioInputs=catalog(sources),defaultOutput=sink['name'] if sink else '',defaultInput=source['name'] if source else '',inputAvailable=bool(source) and not audio_unplugged(source),inputName=audio_label(source) if source else 'No microphone',inputReason='Microphone jack reports unplugged. Reconnect your wired headset.' if unplugged else ('Choose a microphone above.' if sources and not source else 'No active microphone. Check the connection and Device profiles below.' if not sources else ''),inputVolume=audio_volume(source) if source else 0,inputMuted=bool(source.get('mute',False)) if source else False)
    if include_cards:
        try:state['audioCards']=audio_cards()
        except (RuntimeError,OSError,ValueError,subprocess.SubprocessError):state['audioCards']=[]
    return state

def set_audio_device(name,input_device=False):
    if not isinstance(name,str) or not name or len(name)>512 or any(ord(c)<32 for c in name):raise ValueError('Invalid audio device')
    devices=audio_devices('sources' if input_device else 'sinks')
    selected=next((d for d in devices if d['name']==name and (not input_device or not is_monitor(d))),None)
    if selected is None:raise ValueError('Audio device is no longer available')
    if input_device and audio_unplugged(selected):raise ValueError('Microphone jack reports unplugged. Reconnect your wired headset, then select it again.')
    streams=json.loads(run(['pactl','-f','json','list','source-outputs' if input_device else 'sink-inputs']))
    run(['pactl','set-default-source' if input_device else 'set-default-sink',name])
    monitors={value for d in devices if is_monitor(d) for value in (str(d.get('index')),d['name'])} if input_device else set()
    for stream in streams[:128]:
        index=stream.get('index')
        if not str(index).isdigit() or (input_device and str(stream.get('source')) in monitors):continue
        try:run(['pactl','move-source-output' if input_device else 'move-sink-input',str(index),name])
        except RuntimeError:pass # A stream may end while its route is being changed.

def set_input_control(action,value):
    info=json.loads(run(['pactl','-f','json','info']))
    source=next((s for s in audio_devices('sources') if s['name']==info.get('default_source_name') and not is_monitor(s)),None)
    if source is None:raise ValueError('No microphone available')
    return run(['pactl',action,source['name'],value])

def network_snapshot():
    fields=run(['nmcli','-t','-f','STATE,CONNECTIVITY,WIFI','general']).strip().split(':')
    return dict(networkAvailable=True,networkState=fields[0] if fields else 'Unknown',wifiEnabled=fields[-1]=='enabled')

def wifi_scan(rescan=False):
    # NUL separators are not supported by nmcli; escaped colons/backslashes are parsed explicitly.
    lines=run(['nmcli','-t','-f','IN-USE,SSID,SIGNAL,SECURITY','device','wifi','list','--rescan','yes' if rescan else 'no'])
    networks={}
    for line in lines.splitlines():
        fields=re.split(r'(?<!\\):',line)
        if len(fields)<4:continue
        ssid=fields[1].replace('\\:',':').replace('\\\\','\\')
        if not ssid:continue
        item=dict(ssid=ssid,active=fields[0]=='*',signal=int(fields[2] or 0),secure=fields[3] not in ('','--'))
        if ssid not in networks or item['signal']>networks[ssid]['signal']:networks[ssid]=item
    return sorted(networks.values(),key=lambda n:(not n['active'],-n['signal']))[:20]

UDISKS_BLOCK='org.freedesktop.UDisks2.Block'
UDISKS_FILESYSTEM='org.freedesktop.UDisks2.Filesystem'

class DeviceArrivalTracker:
    """Bounded event-only UDisks arrivals; existing disks are not enumerated."""
    def __init__(self):self.objects={};self.announced={}
    @staticmethod
    def text(value,maximum=256):
        return ' '.join(''.join(c if c.isprintable() else ' ' for c in value[:maximum]).split()) if isinstance(value,str) else ''
    @staticmethod
    def unpack(value):return value.unpack() if hasattr(value,'unpack') else value
    def added(self,path,interfaces):
        if not isinstance(path,str) or not re.fullmatch(r'/org/freedesktop/UDisks2/block_devices/[A-Za-z0-9_]{1,256}',path) or not isinstance(interfaces,dict):return None
        old=self.objects.get(path,dict(block={},filesystem=False));entry=dict(block=dict(old['block']),filesystem=old['filesystem'])
        properties=self.unpack(interfaces.get(UDISKS_BLOCK))
        if isinstance(properties,dict):
            for key in ('HintIgnore','HintSystem'):
                value=self.unpack(properties.get(key))
                if type(value) is bool:entry['block'][key]=value
            for key in ('IdLabel','IdUUID','IdUsage','Drive'):
                value=self.unpack(properties.get(key))
                if isinstance(value,str):entry['block'][key]=value[:512]
            device=self.unpack(properties.get('Device'))
            if isinstance(device,(bytes,bytearray,list,tuple)) and len(device)<=4096:
                try:entry['block']['Device']=bytes(device).split(b'\0',1)[0].decode('utf-8','replace')[:512]
                except (TypeError,ValueError):pass
        if UDISKS_FILESYSTEM in interfaces:entry['filesystem']=True
        self.objects.pop(path,None);self.objects[path]=entry
        while len(self.objects)>128:self.objects.pop(next(iter(self.objects)))
        block=entry['block']
        if not entry['filesystem'] or block.get('HintIgnore',True) is not False or block.get('HintSystem',True) is not False:return None
        drive=block.get('Drive','');drive=drive if drive.startswith('/org/freedesktop/UDisks2/drives/') else ''
        key=drive or path
        if key in self.announced:return None
        self.announced[key]=path
        while len(self.announced)>64:self.announced.pop(next(iter(self.announced)))
        device=self.text(block.get('Device',''),512)
        name=self.text(block.get('IdLabel',''),128) or self.text(Path(device).name,128) or 'Removable device'
        return dict(path=path,drive=drive,device=device,name=name,uuid=self.text(block.get('IdUUID',''),128))
    def removed(self,path,interfaces):
        if not isinstance(path,str) or not isinstance(interfaces,(list,tuple)):return
        entry=self.objects.get(path)
        if not entry:return
        if UDISKS_BLOCK in interfaces:self.objects.pop(path,None)
        elif UDISKS_FILESYSTEM in interfaces:entry['filesystem']=False
        key=entry['block'].get('Drive') or path
        if not any(row['filesystem'] and (row['block'].get('Drive') or other)==key for other,row in self.objects.items()):self.announced.pop(key,None)


class SystemServices(QObject):
    changed=Signal();update=Signal(object);notice=Signal(str);incoming=Signal(object);openNotification=Signal(object);deviceArrived=Signal(object)
    def __init__(self,enabled=True):
        super().__init__();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-system');self.audio_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='abstract-audio');self.pending=set();self.pending_lock=threading.Lock();self.desiredVolume=None;self.desiredInputVolume=None;self.desiredOutputDevice=None;self.desiredInputDevice=None;self.audio_refresh_again=False;self.closed=False;self.audio_process=None;self.bus=None
        self.audio_stop=threading.Event();self.audio_process_lock=threading.Lock()
        self.session_actions_enabled=enabled and not bool(os.environ.get('ORBIT_NESTED'))
        self.desiredAudioProfiles={}
        self.audio_profiles_dirty=True
        self.state=dict(audioAvailable=False,volume=0,muted=False,audioName='Audio unavailable',audioOutputs=[],audioInputs=[],defaultOutput='',defaultInput='',inputAvailable=False,inputName='No microphone',inputVolume=0,inputMuted=False,networkAvailable=False,networkState='Network unavailable',wifiEnabled=False,batteryPresent=False,batteryPercent=0,batteryState='',notificationServer=False,wifiNetworks=[],wifiConnecting=False,wifiTarget='',wifiScanning=False,wifiError='')
        self.state['audioCards']=[]
        self.history=[];self.popup={};self.dnd=False;self.update.connect(self.apply);self.incoming.connect(self.receiveNotification)
        if enabled:
            self.refreshAudio();self.refreshNetwork()
            self.bus=BusEvents(self)
            self.audio_thread=threading.Thread(target=self.watchAudio,name='orbit-pulse',daemon=True);self.audio_thread.start()
    values=Property('QVariantMap',lambda s:s.state,notify=changed)
    notifications=Property('QVariantList',lambda s:s.history,notify=changed)
    currentNotification=Property('QVariantMap',lambda s:s.popup,notify=changed)
    doNotDisturb=Property(bool,lambda s:s.dnd,notify=changed)
    @Property(bool,constant=True)
    def canSwitchUser(self):
        from screen_lock import locker_binary
        return bool(self.session_actions_enabled and os.environ.get('ORBIT_NATIVE_CONTROL') and shutil.which('dm-tool') and locker_binary() and Path('/etc/pam.d/swaylock').is_file())
    @Slot()
    def switchUser(self):
        if not self.canSwitchUser:return self.notice.emit('Switch user requires the LightDM login screen and working screen lock')
        def work():
            from screen_lock import launch_and_wait
            # The daemon-ready acknowledgement proves the session is locked
            # before handing control to the login screen. Never skip on error.
            launch_and_wait()
            from native_compositor import NativeCompositor
            if not NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']).status().get('locked'):
                raise RuntimeError('The desktop did not confirm its lock; staying in this session')
            return run(['dm-tool','switch-to-greeter'])
        self.submit('switch-user',work)
    def submit(self,key,work,done=None,on_error=None):
        def task():
            try:return dict(key=key,value=work(),done=done)
            except Exception as e:return dict(key=key,error=str(e),on_error=on_error)
        # Audio must not wait behind network authentication. Each lane has one
        # demand-started worker; existing per-key coalescing bounds slider work.
        audio=key in ('audio','set-volume','mute','output-device','input-device','input-volume','input-mute') or key.startswith('audio-profile:')
        with self.pending_lock:
            if self.closed:return False
            if key in self.pending:
                if key=='audio':self.audio_refresh_again=True
                return False
            self.pending.add(key)
            future=(self.audio_pool if audio else self.pool).submit(task)
        future.add_done_callback(lambda f:self.update.emit(f.result()) if not f.cancelled() and not self.closed else None)
        return True
    @Slot(object)
    def apply(self,result):
        if self.closed:return
        if 'key' not in result:self.state.update(result);self.changed.emit();return
        with self.pending_lock:
            self.pending.discard(result['key'])
            again=result['key']=='audio' and self.audio_refresh_again
            if result['key']=='audio':self.audio_refresh_again=False
        if again:self.refreshAudio()
        if result['key'] in ('connect-wifi','wifi'):
            if result['key']=='connect-wifi':self.state.update(wifiConnecting=False,wifiTarget='')
            else:self.state['wifiScanning']=False
            if 'error' in result:self.state['wifiError']=result['error']
            self.changed.emit()
        if 'error' in result:
            if result['key']=='audio':
                self.state.update(audioAvailable=False,audioName='Audio service unavailable',audioOutputs=[],defaultOutput='',inputAvailable=False,inputName='Audio service unavailable',audioInputs=[],defaultInput='',inputReason='Audio service unavailable. Reconnecting…')
                self.state['audioCards']=[]
                self.changed.emit()
            if result['key'] not in ('audio','network','battery'):self.notice.emit(result['error'])
            if result.get('on_error'):result['on_error']()
            return
        if result.get('done'):result['done'](result['value'])
        elif isinstance(result['value'],dict):self.state.update(result['value']);self.changed.emit()
    @Slot()
    def refreshAudio(self,profiles=False):
        with self.pending_lock:
            if profiles:self.audio_profiles_dirty=True
        self.submit('audio',self.audioSnapshot)
    def audioSnapshot(self):
        # Only the audio worker reads catalogs. Card/server events invalidate
        # profiles; held volume keys do not keep spawning full-card queries.
        with self.pending_lock:
            profiles=self.audio_profiles_dirty;self.audio_profiles_dirty=False
        try:return audio_snapshot(include_cards=profiles)
        except Exception:
            with self.pending_lock:self.audio_profiles_dirty=True
            raise
    @Slot()
    def refreshAudioProfiles(self):self.refreshAudio(True)
    def refreshNetwork(self):self.submit('network',network_snapshot)
    @Slot()
    @Slot(bool)
    def refreshWifi(self,rescan=True):
        with self.pending_lock:
            if self.closed or 'wifi' in self.pending or 'connect-wifi' in self.pending:return
        self.state.update(wifiScanning=True)
        if rescan:self.state['wifiError']=''
        self.changed.emit()
        if not self.submit('wifi',lambda:wifi_scan(rescan),lambda rows:(self.state.update(wifiNetworks=rows),self.changed.emit())):
            self.state['wifiScanning']=False;self.changed.emit()

    def watchAudio(self):
        delay=.5
        while not self.audio_stop.is_set():
            process=None;began=time.monotonic()
            try:
                with self.audio_process_lock:
                    if self.audio_stop.is_set():break
                    process=subprocess.Popen(['pactl','subscribe'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
                    self.audio_process=process
                self.refreshAudio(True)
                for line in process.stdout:
                    if self.audio_stop.is_set():break
                    if any(event in line for event in ('sink','source','server','card')):delay=.5;self.refreshAudio('server' in line or 'card' in line)
            except (OSError,RuntimeError):pass
            finally:
                if process:
                    try:
                        if process.poll() is None:process.terminate()
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait(timeout=2)
                    except OSError:pass
                    if process.stdout:process.stdout.close()
                    with self.audio_process_lock:
                        if self.audio_process is process:self.audio_process=None
            if time.monotonic()-began>5:delay=.5
            if self.audio_stop.wait(delay):break
            delay=min(30,delay*2)
    @Slot(int)
    def setVolume(self,value):
        value=max(0,min(100,value));self.desiredVolume=value
        def done(_):
            self.refreshAudio()
            if self.desiredVolume!=value:self.setVolume(self.desiredVolume)
        self.submit('set-volume',lambda:run(['pactl','set-sink-volume','@DEFAULT_SINK@',f'{value}%']),done,lambda:done(None))
    @Slot()
    def toggleMute(self):self.submit('mute',lambda:run(['pactl','set-sink-mute','@DEFAULT_SINK@','toggle']),lambda _:self.refreshAudio())
    @Slot(str)
    def setOutputDevice(self,name):
        self.desiredOutputDevice=name
        def done(_):
            self.refreshAudio()
            if self.desiredOutputDevice!=name:self.setOutputDevice(self.desiredOutputDevice)
        self.submit('output-device',lambda:set_audio_device(name),done,lambda:done(None))
    @Slot(str)
    def setInputDevice(self,name):
        self.desiredInputDevice=name
        def done(_):
            self.refreshAudio()
            if self.desiredInputDevice!=name:self.setInputDevice(self.desiredInputDevice)
        self.submit('input-device',lambda:set_audio_device(name,True),done,lambda:done(None))
    @Slot(str,str)
    def setAudioProfile(self,card_name,profile_name):
        if not any(c['name']==card_name for c in self.state['audioCards']):return self.notice.emit('Audio device is no longer available')
        self.desiredAudioProfiles[card_name]=profile_name
        def done(_):
            self.refreshAudio(True)
            desired=self.desiredAudioProfiles.pop(card_name,None)
            if desired is not None and desired!=profile_name:self.setAudioProfile(card_name,desired)
        self.submit('audio-profile:'+card_name,lambda:set_audio_profile(card_name,profile_name),done,lambda:done(None))
    @Slot(int)
    def setInputVolume(self,value):
        value=max(0,min(100,value));self.desiredInputVolume=value
        def done(_):
            self.refreshAudio()
            if self.desiredInputVolume!=value:self.setInputVolume(self.desiredInputVolume)
        self.submit('input-volume',lambda:set_input_control('set-source-volume',f'{value}%'),done,lambda:done(None))
    @Slot()
    def toggleInputMute(self):self.submit('input-mute',lambda:set_input_control('set-source-mute','toggle'),lambda _:self.refreshAudio())
    @Slot(bool)
    def setWifi(self,enabled):self.submit('wifi-radio',lambda:run(['nmcli','radio','wifi','on' if enabled else 'off']),lambda _:self.refreshNetwork())
    @Slot(str,str)
    def connectWifi(self,ssid,password):
        if not ssid or len(ssid)>128 or '\n' in password or len(password)>128:return
        with self.pending_lock:
            if self.closed or 'connect-wifi' in self.pending:return
        self.state.update(wifiConnecting=True,wifiTarget=ssid,wifiError='');self.changed.emit()
        def work():
            if not password:return run(['nmcli','--wait','10','device','wifi','connect',ssid])
            fd,path=tempfile.mkstemp(prefix='orbit-wifi-')
            try:
                with os.fdopen(fd,'w') as handle:handle.write('802-11-wireless-security.psk:'+password+'\n')
                return run(['nmcli','--wait','10','--passwd-file',path,'device','wifi','connect',ssid])
            finally:os.unlink(path)
        if not self.submit('connect-wifi',work,lambda _:(self.notice.emit('Network connected'),self.refreshNetwork(),self.refreshWifi(False))):
            self.state.update(wifiConnecting=False,wifiTarget='');self.changed.emit()
    @Slot(str)
    def power(self,action):
        # Called only by the explicit confirmation control, never from model output.
        if os.environ.get('ORBIT_NESTED'):return self.notice.emit('Power actions are disabled in the nested test session')
        choices={'suspend':['systemctl','suspend'],'reboot':['systemctl','reboot'],'shutdown':['systemctl','poweroff']}
        if action in choices:self.submit('power',lambda:run(choices[action]))
    @Slot()
    def lock(self):
        if os.environ.get('SWAYSOCK') or os.environ.get('ORBIT_NATIVE_CONTROL'):
            from screen_lock import locker_binary,launch_and_wait
            if not Path('/etc/pam.d/swaylock').exists():return self.notice.emit('Install the system swaylock PAM configuration before using lock')
            if os.environ.get('ORBIT_NESTED'):return self.notice.emit('Screen locking is disabled in nested preview sessions')
            if not locker_binary():return self.notice.emit('Install swaylock before using lock')
            with self.pending_lock:
                if self.closed or 'lock' in self.pending:return
                self.pending.add('lock')
            def start():
                try:launch_and_wait();result=dict(key='lock',value=None)
                except Exception as error:result=dict(key='lock',error=str(error))
                if not self.closed:self.update.emit(result)
            # Lock immediately even if Wi-Fi or an audio operation is busy.
            # This thread ends on readiness/failure; there is no idle worker.
            self.lock_thread=threading.Thread(target=start,name='orbit-lock-start',daemon=True)
            self.lock_thread.start();return
        self.submit('lock',lambda:run(['loginctl','lock-session']))
    @Slot(bool)
    def setDnd(self,value):self.dnd=value;self.popup={};self.changed.emit()
    @Slot(object)
    def receiveNotification(self,note):
        if note.get('close'):
            ident=note['close'];self.history=[n for n in self.history if n['id']!=ident]
            if self.popup.get('id')==ident:self.popup={}
        else:
            self.history=[n for n in self.history if n['id']!=note['id']];self.history.insert(0,note);self.history=self.history[:50]
            if not self.dnd:self.popup=note
        self.changed.emit()
    @Slot()
    def hideNotification(self):self.popup={};self.changed.emit()
    @Slot(int)
    def activateNotification(self,ident):
        self.invokeNotificationAction(ident,'default')
    @Slot(int,str)
    def invokeNotificationAction(self,ident,action):
        note=next((n for n in self.history if n['id']==ident),None)
        if not note:return
        offered=any(a['key']==action for a in note.get('actions',[]))
        if offered:
            if not self.bus or not self.bus.invokeAction(note,action):
                self.notice.emit('This notification action is no longer available');return
        elif action=='default':self.openNotification.emit(note)
        else:return
        self.hideNotification()
        if not note.get('resident',False):self.dismissNotification(ident)
    @Slot(int)
    def dismissNotification(self,ident):
        self.receiveNotification({'close':ident})
        if self.bus:self.bus.closeNotification(ident,2)
    @Slot()
    def clearNotifications(self):
        for note in self.history[:]:self.dismissNotification(note['id'])
    def close(self):
        with self.pending_lock:
            if self.closed:return
            self.closed=True;self.pending.clear()
            self.state.update(wifiConnecting=False,wifiTarget='',wifiScanning=False,wifiError='')
        # Cancel both queues before joining either lane. No deferred volume or
        # connection command may begin while shutdown waits for another worker.
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.audio_pool.shutdown(wait=False,cancel_futures=True)
        self.audio_stop.set()
        with self.audio_process_lock:
            process=self.audio_process
            if process:
                try:process.terminate()
                except OSError:pass
        watcher=getattr(self,'audio_thread',None)
        if watcher:
            watcher.join(timeout=3)
            if watcher.is_alive() and process:
                try:process.kill()
                except OSError:pass
                watcher.join(timeout=2)
        if self.bus:self.bus.close()
        lock_thread=getattr(self,'lock_thread',None)
        if lock_thread:lock_thread.join(timeout=9)
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.audio_pool.shutdown(wait=True,cancel_futures=True)

NOTIFICATION_XML='''<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface></node>'''

class BusEvents:
    def __init__(self,owner):
        self.owner=owner;self.loop=None;self.connection=None;self.owns_notifications=False;self.counter=0;self.records={};self.records_lock=threading.RLock();self.device_tracker=DeviceArrivalTracker();self.system_connection=None;self.device_subscriptions=[]
        self.thread=threading.Thread(target=self.run,name='orbit-dbus',daemon=True);self.thread.start()
    def run(self):
        try:
            import sys
            if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
            import gi;gi.require_version('Gio','2.0');from gi.repository import Gio,GLib
            self.GLib=GLib;self.Gio=Gio;context=GLib.MainContext.new();context.push_thread_default();self.loop=GLib.MainLoop.new(context,False)
            self.connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
            system=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
            system.signal_subscribe('org.freedesktop.NetworkManager','org.freedesktop.DBus.Properties','PropertiesChanged',None,None,Gio.DBusSignalFlags.NONE,lambda *_:self.owner.refreshNetwork())
            def battery(*_):
                try:
                    reply=system.call_sync('org.freedesktop.UPower','/org/freedesktop/UPower/devices/DisplayDevice','org.freedesktop.DBus.Properties','GetAll',GLib.Variant('(s)',('org.freedesktop.UPower.Device',)),None,Gio.DBusCallFlags.NONE,2000,None)
                    values=reply.unpack()[0];self.owner.update.emit(dict(batteryPresent=bool(values.get('IsPresent',False)),batteryPercent=round(values.get('Percentage',0)),batteryState=str(values.get('State',0))))
                except Exception:pass
            system.signal_subscribe('org.freedesktop.UPower','org.freedesktop.DBus.Properties','PropertiesChanged','/org/freedesktop/UPower/devices/DisplayDevice',None,Gio.DBusSignalFlags.NONE,battery);battery()
            # Observe only newly added filesystem objects. No GetManagedObjects
            # scan, polling timer, automount, helper daemon or filesystem writes.
            self.system_connection=system
            try:
                self.device_subscriptions.append(system.signal_subscribe('org.freedesktop.UDisks2','org.freedesktop.DBus.ObjectManager','InterfacesAdded','/org/freedesktop/UDisks2',None,Gio.DBusSignalFlags.NONE,self.device_added))
                self.device_subscriptions.append(system.signal_subscribe('org.freedesktop.UDisks2','org.freedesktop.DBus.ObjectManager','InterfacesRemoved','/org/freedesktop/UDisks2',None,Gio.DBusSignalFlags.NONE,self.device_removed))
            except Exception:pass

            result=self.connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.freedesktop.Notifications',4)),None,Gio.DBusCallFlags.NONE,2000,None).unpack()[0]
            if result==1:
                self.owns_notifications=True;info=Gio.DBusNodeInfo.new_for_xml(NOTIFICATION_XML)
                self.registration=self.connection.register_object('/org/freedesktop/Notifications',info.interfaces[0],self.method,None,None)
                self.owner.update.emit(dict(notificationServer=True))
            self.loop.run();context.pop_thread_default()
        except Exception:pass
    def device_added(self,connection,sender,path,interface,member,params):
        if self.owner.closed:return
        try:
            object_path,interfaces=params.unpack();arrival=self.device_tracker.added(object_path,interfaces)
            if arrival:self.owner.deviceArrived.emit(arrival)
        except (TypeError,ValueError,AttributeError):pass
    def device_removed(self,connection,sender,path,interface,member,params):
        try:
            object_path,interfaces=params.unpack();self.device_tracker.removed(object_path,interfaces)
        except (TypeError,ValueError,AttributeError):pass
    def method(self,connection,sender,path,interface,method,params,invocation):
        GLib=self.GLib
        if method=='GetCapabilities':invocation.return_value(GLib.Variant('(as)',(['body','actions'],)))
        elif method=='GetServerInformation':invocation.return_value(GLib.Variant('(ssss)',('Mellipi','Mellipi','0.1.8','1.2')))
        elif method=='Notify':
            app,replaces,icon,summary,body,actions,hints,timeout=params.unpack()
            with self.records_lock:
                if replaces in self.records and self.records[replaces]['sender']==sender:ident=replaces
                else:
                    self.counter+=1
                    while self.counter in self.records:self.counter+=1
                    ident=self.counter
                entry=hints.get('desktop-entry','');entry=entry if isinstance(entry,str) and len(entry)<=250 and not any(c in entry for c in ('/','\\','\0')) else ''
                choices=[];seen=set()
                for i in range(0,min(len(actions)-1,32),2):
                    key,label=actions[i:i+2]
                    if key and len(key)<=1024 and key not in seen:choices.append(dict(key=key,label=label[:100]));seen.add(key)
                note=dict(id=ident,app=app[:100],summary=summary[:200],body=body[:2000],sender=sender,desktopEntry=entry,actions=choices,resident=hints.get('resident') is True,timeout=max(1500,min(15000,timeout if timeout>0 else 5000)))
                self.records.pop(ident,None);self.records[ident]=note
                while len(self.records)>50:self.records.pop(next(iter(self.records)))
            self.owner.incoming.emit(note)
            invocation.return_value(GLib.Variant('(u)',(ident,)))
        elif method=='CloseNotification':
            ident=params.unpack()[0]
            with self.records_lock:owned=self.records.get(ident,{}).get('sender')==sender
            if owned:self.owner.incoming.emit({'close':ident});self.closeNotification(ident,3)
            invocation.return_value(GLib.Variant('()',()))
        else:invocation.return_dbus_error('org.freedesktop.DBus.Error.UnknownMethod','Unsupported method')
    def closeNotification(self,ident,reason):
        if type(ident) is not int or ident<0:return
        with self.records_lock:self.records.pop(ident,None)
        if self.owns_notifications and self.connection:
            self.connection.emit_signal(None,'/org/freedesktop/Notifications','org.freedesktop.Notifications','NotificationClosed',self.GLib.Variant('(uu)',(ident,reason)))
    def invokeAction(self,note,action):
        with self.records_lock:
            current=self.records.get(note['id'])
            if current!=note or not any(a['key']==action for a in current.get('actions',[])):return False
            if not self.owns_notifications or not self.connection:return False
            self.connection.emit_signal(note['sender'],'/org/freedesktop/Notifications','org.freedesktop.Notifications','ActionInvoked',self.GLib.Variant('(us)',(note['id'],action)))
        return True
    def close(self):
        if self.system_connection:
            for subscription in self.device_subscriptions:
                try:self.system_connection.signal_unsubscribe(subscription)
                except Exception:pass
            self.device_subscriptions=[]
        if self.owns_notifications and self.connection:
            try:
                self.connection.unregister_object(self.registration)
                self.connection.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReleaseName',self.GLib.Variant('(s)',('org.freedesktop.Notifications',)),None,self.Gio.DBusCallFlags.NONE,1000,None)
            except Exception:pass
        if self.loop:self.loop.quit()
        self.thread.join(timeout=3)

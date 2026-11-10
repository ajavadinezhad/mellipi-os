"""Rate-limited hardware keys using existing controls; no extra service process."""
import time
from qt_compat import QObject,Slot,QTimer
from hardware_bindings import ACTIONS

class HardwareKeys(QObject):
    def __init__(self,system,media,brightness,notice,parent=None):
        super().__init__(parent);self.system=system;self.media=media;self.brightness=brightness;self.notice=notice
        self.targets={};self.last={};self.timers={}
        for kind in ('volume','brightness'):
            timer=QTimer(self);timer.setSingleShot(True);timer.setInterval(80)
            timer.timeout.connect(lambda k=kind:self.flush(k));self.timers[kind]=timer
    @Slot(str)
    def handle(self,action):
        if action not in ACTIONS:return
        if action in ('volume-up','volume-down','brightness-up','brightness-down'):
            kind,direction=action.rsplit('-',1);state=self.system.values if kind=='volume' else self.brightness.state
            available=state.get('audioAvailable') if kind=='volume' else state.get('available')
            if not available:return self.notice('No audio output is available' if kind=='volume' else 'Brightness control is unavailable')
            now=time.monotonic();base=self.targets.get(kind,state.get('volume' if kind=='volume' else 'percent',0)) if now-self.last.get(kind,0)<1 else state.get('volume' if kind=='volume' else 'percent',0)
            self.targets[kind]=max(0 if kind=='volume' else 1,min(100,int(base)+(5 if direction=='up' else -5)));self.last[kind]=now
            if not self.timers[kind].isActive():self.timers[kind].start()
        elif action=='volume-mute':self.system.toggleMute()
        elif action=='microphone-mute':
            if self.system.values.get('inputAvailable'):self.system.toggleInputMute()
            else:self.notice('No connected microphone is available')
        elif action=='media-play-pause':self.media.playPause()
        elif action=='media-pause':
            if self.media.state.get('playing'):self.media.playPause()
        elif action=='media-stop':self.media.stop()
        elif action=='media-next':self.media.next()
        elif action=='media-previous':self.media.previous()
    def flush(self,kind):
        value=self.targets[kind]
        if kind=='volume':self.system.setVolume(value)
        else:self.brightness.setBrightness(value)
        self.notice(('Volume' if kind=='volume' else 'Brightness')+f' {value}%')
    def close(self):
        for timer in self.timers.values():timer.stop()

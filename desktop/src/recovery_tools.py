"""Demand-only GUI adapter for backups and signed-package recovery guidance."""
import json,os,threading,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot,QDesktopServices,QUrl
from backup_core import create_backup,inspect_backup,restore_files,queue_settings_restore,roots
from recovery_packages import load_checkpoint,save_checkpoint
from backup_picker import picker_environment,validate_selection,MAX_OUTPUT,MAX_SELECTIONS
from project_paths import SOURCE_ROOT

class RecoveryTools(QObject):
    changed=Signal();completed=Signal(object)
    def __init__(self,parent=None,environment=None):
        super().__init__(parent);self.environment=dict(os.environ if environment is None else environment);self._executor=None;self._cancel=threading.Event();self._closed=False;self._picker=None;self._pickerLock=threading.Lock()
        home=self.environment.get('HOME',str(Path.home()));self._state={'busy':False,'operation':'','message':'','error':'','backupParent':home,'backupPath':'','restoreParent':home,'personalFiles':[],'preview':{},'checkpoint':{},'resultPath':'','restorePending':False}
        try:self._state['checkpoint']=load_checkpoint(self.environment);self._state['restorePending']=(roots(self.environment)[1]/'pending-settings-restore.json').is_file()
        except (OSError,ValueError,json.JSONDecodeError) as e:self._state['error']=str(e)
        self.completed.connect(self._apply)
    state=Property('QVariantMap',lambda s:dict(s._state),notify=changed)
    def _run(self,kind,work):
        if self._closed or self._state['busy']:return
        self._state.update(busy=True,operation=kind,error='',message='');self._cancel.clear();self.changed.emit()
        if self._executor is None:self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mellipi-backup')
        def task():
            try:result={'kind':kind,'value':work()}
            except Exception as e:result={'kind':kind,'error':str(e)}
            if not self._closed:self.completed.emit(result)
        self._executor.submit(task)
    @Slot(object)
    def _apply(self,result):
        if self._closed:return
        self._state.update(busy=False,operation='',error=result.get('error',''))
        if 'value' in result:
            v=result['value'];kind=result['kind']
            if kind=='backup':self._state.update(backupPath=v['path'],resultPath=v['path'],preview={},message=f'Backup saved: {v["files"]} files, {v["directories"]} folders.')
            elif kind=='inspect':self._state.update(preview=v,message=f'Backup verified: {v["files"]} files, {v["directories"]} folders.')
            elif kind=='restore':self._state.update(resultPath=v['path'],message='Files restored to a new folder. Existing files were kept.')
            elif kind=='settings':self._state.update(restorePending=True,message=v['message'])
            elif kind=='working':self._state.update(checkpoint=v,message='Working desktop versions saved. Recovery instructions are below.')
            elif kind.startswith('picker:'):
                key=kind.split(':',1)[1];paths=v
                if paths:
                    if key in ('personal','files'):
                        merged=list(dict.fromkeys([*self._state['personalFiles'],*paths]))
                        if len(merged)>MAX_SELECTIONS:self._state['error']='Choose up to 128 files or folders at once.'
                        else:self._state['personalFiles']=merged
                    else:
                        self._state[key]=paths[0]
                        if key=='backupPath':self._state['preview']={}
        self.changed.emit()
    @Slot(str,str)
    def setPath(self,key,value):
        if self._state['busy'] or key not in ('backupParent','backupPath','restoreParent') or not isinstance(value,str) or len(value)>4096:return
        self._state[key]=value
        if key=='backupPath':self._state['preview']={}
        self.changed.emit()
    @Slot(str)
    def chooseDirectory(self,key):
        if self._state['busy'] or key not in ('backupParent','backupPath','restoreParent','personal'):return
        self._run('picker:'+key,lambda:self._pick('directory'))
    @Slot()
    def chooseFiles(self):
        if self._state['busy']:return
        self._run('picker:files',lambda:self._pick('files'))
    def _pick(self,mode):
        from qt5_a11y_runtime import scoped_environment
        env=scoped_environment(picker_environment(self.environment))
        if not env.get('WAYLAND_DISPLAY') and not env.get('DISPLAY'):raise ValueError('Open the file chooser from a graphical desktop session.')
        initial=self.environment.get('HOME',str(Path.home()))
        with self._pickerLock:
            if self._closed or self._cancel.is_set():return []
            process=subprocess.Popen([sys.executable,'-I',str(SOURCE_ROOT/'backup_picker.py'),'--mode',mode,'--initial',initial],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,text=True)
            self._picker=process
        try:
            try:output,_=process.communicate(timeout=300)
            except subprocess.TimeoutExpired:
                process.kill();process.communicate();raise ValueError('The file chooser timed out. Open it again.') from None
            if self._cancel.is_set():return []
            if process.returncode!=0 or len(output.encode('utf-8'))>MAX_OUTPUT:raise ValueError('The file chooser could not complete. Open it again.')
            result=json.loads(output)
            if isinstance(result,dict) and result.get('status')=='error':raise ValueError('Choose fewer valid local files, or the original folder instead of a symlink.')
            return validate_selection(result,mode)
        finally:
            with self._pickerLock:
                if self._picker is process:self._picker=None
    def _cancel_picker(self):
        with self._pickerLock:process=self._picker
        if process is not None and process.poll() is None:
            try:process.kill()
            except ProcessLookupError:pass
    @Slot()
    def clearFiles(self):
        if not self._state['busy']:self._state['personalFiles']=[];self.changed.emit()
    @Slot()
    def create(self):
        parent=self._state['backupParent'];personal=list(self._state['personalFiles']);self._run('backup',lambda:create_backup(parent,self.environment,personal,self._cancel.is_set))
    @Slot()
    def inspect(self):
        path=self._state['backupPath']
        def work():
            m=inspect_backup(path,self._cancel.is_set);return {'verified':True,'files':sum(r.get('type','file')=='file' for r in m['files']),'directories':sum(r.get('type')=='directory' for r in m['files']),'bytes':m['bytes'],'settings':sum(r['kind']=='settings' for r in m['files']),'personal':sum(r['kind']=='personal' for r in m['files'])}
        self._run('inspect',work)
    @Slot()
    def restore(self):
        path=self._state['backupPath'];parent=self._state['restoreParent'];self._run('restore',lambda:restore_files(path,parent,self._cancel.is_set))
    @Slot()
    def queueSettings(self):
        path=self._state['backupPath'];self._run('settings',lambda:queue_settings_restore(path,self.environment,self._cancel.is_set))
    @Slot()
    def cancelSettings(self):
        if self._state['busy']:return
        try:
            path=roots(self.environment)[1]/'pending-settings-restore.json'
            if path.is_symlink():raise ValueError('Unsafe settings restore request')
            path.unlink(missing_ok=True);self._state.update(restorePending=False,message='Scheduled settings restore cancelled.',error='')
        except (OSError,ValueError) as e:self._state['error']=str(e)
        self.changed.emit()
    @Slot()
    def saveWorking(self):self._run('working',lambda:save_checkpoint(self.environment))
    @Slot()
    def cancel(self):self._cancel.set();self._cancel_picker()
    @Slot()
    def openResult(self):
        path=Path(self._state['resultPath'])
        if self._state['resultPath'] and path.is_dir():QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def close(self):
        self._closed=True;self._cancel.set();self._cancel_picker()
        if self._executor:self._executor.shutdown(wait=False,cancel_futures=True)

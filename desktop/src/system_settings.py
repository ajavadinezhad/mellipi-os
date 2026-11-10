"""On-demand account and clock administration through distro-owned services.

AccountsService and timedated retain privilege checks and polkit prompts. No
shell commands, passwords in argv, or background polling are used here.
"""
import ctypes,ctypes.util,datetime,os,re,secrets,string,threading,unicodedata

ACCOUNTS='org.freedesktop.Accounts'
ACCOUNT_PATH='/org/freedesktop/Accounts'
USER=ACCOUNTS+'.User'
TIME='org.freedesktop.timedate1'
TIME_PATH='/org/freedesktop/timedate1'
LOGIN='org.freedesktop.login1'
LOGIN_PATH='/org/freedesktop/login1'
PROPERTIES='org.freedesktop.DBus.Properties'
_CRYPT_LOCK=threading.Lock()

class ServiceError(RuntimeError):pass

class SystemBus:
    def call(self,service,path,interface,method,signature,args,interactive=False):
        from gi.repository import Gio,GLib
        connection=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
        flags=Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION if interactive else Gio.DBusCallFlags.NONE
        try:
            return connection.call_sync(service,path,interface,method,GLib.Variant(signature,args),None,flags,120000 if interactive else 5000,None).unpack()
        except GLib.Error as error:
            # Do not propagate call arguments, password hashes, or service dumps.
            name=Gio.DBusError.get_remote_error(error) or ''
            if any(word in name for word in ('PermissionDenied','NotAuthorized','AccessDenied','InteractiveAuthorizationRequired','Cancelled')):
                raise ServiceError('Authorization was cancelled or denied. No change was confirmed.') from None
            if any(word in name for word in ('ServiceUnknown','NameHasNoOwner','UnknownInterface','UnknownObject')):
                label='AccountsService' if service==ACCOUNTS else 'the system date and time service'
                raise ServiceError('Cannot reach '+label+'. Check that its distribution package is installed.') from None
            raise ServiceError('The system service could not complete this request. Refresh to check its current state.') from None

def valid_name(value,username=False):
    if not isinstance(value,str):raise ValueError('Enter a valid name.')
    if any(unicodedata.category(c).startswith('C') for c in value):raise ValueError('Names cannot contain control characters.')
    value=value.strip()
    if username:
        if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}',value):raise ValueError('Use a lowercase login name of 1–31 letters, numbers, underscores or hyphens.')
        if value in ('root','nobody','daemon'):raise ValueError('Choose another login name.')
    elif not value or len(value)>80 or any(unicodedata.category(c).startswith('C') or c==':' for c in value):
        raise ValueError('Enter a display name of 1–80 characters without control characters or colons.')
    return value

def password_hash(password,confirmation):
    if not isinstance(password,str) or password!=confirmation:raise ValueError('The passwords do not match.')
    if len(password)<8 or len(password.encode())>1024 or any(c in password for c in '\0\r\n'):
        raise ValueError('Use a password of at least 8 characters without line breaks.')
    library=ctypes.util.find_library('crypt')
    if not library:raise ServiceError('The system password hashing library is unavailable.')
    # SHA-512 crypt is supported by AccountsService/shadow on the Noble target.
    # libcrypt's return buffer is shared: serialize calls, copy immediately.
    with _CRYPT_LOCK:
        crypt=ctypes.CDLL(library).crypt;crypt.argtypes=[ctypes.c_char_p,ctypes.c_char_p];crypt.restype=ctypes.c_char_p
        salt='$6$rounds=100000$'+''.join(secrets.choice(string.ascii_letters+string.digits+'./') for _ in range(16))+'$'
        result=crypt(password.encode(),salt.encode())
        if not result or not result.startswith(b'$6$'):raise ServiceError('The system could not prepare a password securely.')
        return result.decode('ascii')

def _plain(value):
    if hasattr(value,'unpack'):return _plain(value.unpack())
    if isinstance(value,dict):return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_plain(v) for v in value]
    return value

class SystemSettingsBackend:
    def __init__(self,bus=None,uid=None,hasher=password_hash):
        self.bus=bus or SystemBus();self.uid=os.getuid() if uid is None else uid;self.hasher=hasher
    def call(self,*args,**kwargs):return self.bus.call(*args,**kwargs)
    def props(self,service,path,interface):return _plain(self.call(service,path,PROPERTIES,'GetAll','(s)',(interface,))[0])
    def users(self):
        paths=list(self.call(ACCOUNTS,ACCOUNT_PATH,ACCOUNTS,'ListCachedUsers','()',())[0])[:64]
        own=self.call(ACCOUNTS,ACCOUNT_PATH,ACCOUNTS,'FindUserById','(x)',(self.uid,))[0]
        if own not in paths:paths.append(own)
        try:
            sessions=self.call(LOGIN,LOGIN_PATH,LOGIN+'.Manager','ListSessions','()',())[0]
            signed_in={int(row[1]) for row in sessions};sessions_known=True
        except ServiceError:
            signed_in={self.uid};sessions_known=False
        rows=[]
        for path in paths:
            if not re.fullmatch(r'/org/freedesktop/Accounts/User[0-9]+',str(path)):continue
            v=self.props(ACCOUNTS,path,USER);uid=int(v.get('Uid',-1))
            if v.get('SystemAccount',False) or uid<1000:continue
            rows.append(dict(id=uid,name=str(v.get('UserName',''))[:80],displayName=str(v.get('RealName',''))[:80],administrator=v.get('AccountType')==1,locked=bool(v.get('Locked')),loggedIn=uid in signed_in,sessionsKnown=sessions_known,current=uid==self.uid,path=path))
        return sorted(rows,key=lambda r:(not r['current'],r['name']))
    def selected(self,uid):
        if type(uid) is not int or uid<1000:raise ValueError('Choose a regular local user account.')
        rows=self.users();row=next((r for r in rows if r['id']==uid),None)
        if not row:raise ValueError('This account is no longer available. Refresh the list.')
        return row,rows
    def update_user(self,uid,name,administrator):
        if type(administrator) is not bool:raise ValueError('Choose a valid account type.')
        name=valid_name(name);row,rows=self.selected(uid)
        if row['administrator'] and not administrator and sum(r['administrator'] and not r['locked'] for r in rows)<=1:
            raise ValueError('Keep at least one unlocked administrator account.')
        if row['current'] and row['administrator']!=administrator:raise ValueError('Change your own account type from another administrator account.')
        if name!=row['displayName']:self.call(ACCOUNTS,row['path'],USER,'SetRealName','(s)',(name,),interactive=True)
        if administrator!=row['administrator']:self.call(ACCOUNTS,row['path'],USER,'SetAccountType','(i)',(int(administrator),),interactive=True)
        return self.users()
    def create_user(self,username,name,password,confirmation,administrator):
        username=valid_name(username,True);name=valid_name(name)
        if type(administrator) is not bool:raise ValueError('Choose a valid account type.')
        if any(r['name']==username for r in self.users()):raise ValueError('This login name is already in use.')
        encrypted=self.hasher(password,confirmation)
        path=self.call(ACCOUNTS,ACCOUNT_PATH,ACCOUNTS,'CreateUser','(ssi)',(username,name,int(administrator)),interactive=True)[0]
        if not re.fullmatch(r'/org/freedesktop/Accounts/User[0-9]+',str(path)):raise ServiceError('The service returned an invalid account. Refresh the list.')
        try:
            self.call(ACCOUNTS,path,USER,'SetLocked','(b)',(True,),interactive=True)
            self.call(ACCOUNTS,path,USER,'SetPassword','(ss)',(encrypted,''),interactive=True)
        except Exception:
            # Never delete a partially configured account or its home directory.
            try:self.call(ACCOUNTS,path,USER,'SetLocked','(b)',(True,),interactive=True)
            except Exception:raise ServiceError('The account was created but password setup was not confirmed. Refresh and check its locked state before use.') from None
            raise ServiceError('The account was created and kept locked. Set its password to finish setup.') from None
        return self.users()
    def reset_password(self,uid,password,confirmation):
        row,_=self.selected(uid)
        if row['current']:raise ValueError('Use Change my password so PAM can check your current password.')
        encrypted=self.hasher(password,confirmation)
        self.call(ACCOUNTS,row['path'],USER,'SetPassword','(ss)',(encrypted,''),interactive=True)
        return self.users()
    def delete_user(self,uid):
        row,rows=self.selected(uid)
        if row['current']:raise ValueError('You cannot remove your signed-in account.')
        if not row['sessionsKnown']:raise ServiceError('Cannot check active sign-ins. Restore the login service before removing an account.')
        if row['loggedIn']:raise ValueError('This user must sign out before its account can be removed.')
        if row['administrator'] and sum(r['administrator'] and not r['locked'] for r in rows)<=1:raise ValueError('Keep at least one unlocked administrator account.')
        self.call(ACCOUNTS,ACCOUNT_PATH,ACCOUNTS,'DeleteUser','(xb)',(uid,False),interactive=True)
        return self.users()
    def clock(self):
        v=self.props(TIME,TIME_PATH,TIME)
        zones=self.call(TIME,TIME_PATH,TIME,'ListTimezones','()',())[0]
        zones=sorted(set(z for z in zones if isinstance(z,str) and len(z)<100 and re.fullmatch(r'[A-Za-z0-9_+./-]+',z) and '..' not in z.split('/')))[:1024]
        return dict(timezone=v.get('Timezone',''),ntp=bool(v.get('NTP')),canNtp=bool(v.get('CanNTP')),synchronized=bool(v.get('NTPSynchronized')),zones=zones)
    def set_timezone(self,zone):
        if not isinstance(zone,str) or zone not in self.clock()['zones']:raise ValueError('Choose an installed time zone.')
        self.call(TIME,TIME_PATH,TIME,'SetTimezone','(sb)',(zone,True),interactive=True)
        return self.clock()
    def set_ntp(self,enabled):
        if type(enabled) is not bool:raise ValueError('Choose a valid automatic-time setting.')
        if not self.clock()['canNtp']:raise ServiceError('No network time service is available. Install systemd-timesyncd or another supported service.')
        self.call(TIME,TIME_PATH,TIME,'SetNTP','(bb)',(enabled,True),interactive=True)
        return self.clock()
    def set_time(self,value):
        if not isinstance(value,str) or len(value)>32:raise ValueError('Enter UTC date and time as YYYY-MM-DD HH:MM.')
        try:stamp=datetime.datetime.strptime(value,'%Y-%m-%d %H:%M').replace(tzinfo=datetime.timezone.utc)
        except ValueError:raise ValueError('Enter UTC date and time as YYYY-MM-DD HH:MM.') from None
        if not 2000<=stamp.year<=2100:raise ValueError('Choose a year between 2000 and 2100.')
        if self.clock()['ntp']:raise ValueError('Turn automatic time off before setting the clock manually.')
        self.call(TIME,TIME_PATH,TIME,'SetTime','(xbb)',(int(stamp.timestamp()*1_000_000),False,True),interactive=True)
        return self.clock()

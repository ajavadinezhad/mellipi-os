"""Service contracts and failure paths; no real system bus mutations."""
import unittest
from system_settings import ACCOUNTS,ACCOUNT_PATH,USER,TIME,PROPERTIES,SystemSettingsBackend,ServiceError,password_hash,valid_name

class Bus:
    def __init__(self):
        self.calls=[];self.fail='';self.records={1000:dict(Uid=1000,UserName='alice',RealName='Alice',AccountType=1,Locked=False,LoggedIn=True,SystemAccount=False),1001:dict(Uid=1001,UserName='bob',RealName='Bob',AccountType=0,Locked=False,LoggedIn=False,SystemAccount=False)}
        self.sessions=[('c1',1000,'alice','seat0','/org/freedesktop/login1/session/c1')];self.clock=dict(Timezone='Etc/UTC',NTP=True,CanNTP=True,NTPSynchronized=True)
    def call(self,service,path,interface,method,signature,args,interactive=False):
        self.calls.append((method,args,interactive,signature))
        if method==self.fail:raise ServiceError('Authorization was cancelled or denied. No change was confirmed.')
        if method=='ListCachedUsers':return ([ACCOUNT_PATH+'/User'+str(i) for i in self.records],)
        if method=='FindUserById':return (ACCOUNT_PATH+'/User'+str(args[0]),)
        if method=='ListSessions':return (self.sessions,)
        if method=='GetAll':return (dict(self.clock if service==TIME else self.records[int(path.split('User')[-1])]),)
        if method=='ListTimezones':return (['Etc/UTC','America/New_York','Europe/Paris'],)
        if method=='CreateUser':
            self.records[1002]=dict(Uid=1002,UserName=args[0],RealName=args[1],AccountType=args[2],Locked=True,LoggedIn=False,SystemAccount=False);return (ACCOUNT_PATH+'/User1002',)
        if method in ('SetLocked','SetPassword','SetRealName','SetAccountType'):
            row=self.records[int(path.split('User')[-1])];key={'SetLocked':'Locked','SetPassword':'Locked','SetRealName':'RealName','SetAccountType':'AccountType'}[method];row[key]=False if method=='SetPassword' else args[0];return ()
        if method=='DeleteUser':del self.records[args[0]];return ()
        if method=='SetNTP':self.clock['NTP']=args[0];return ()
        if method=='SetTimezone':self.clock['Timezone']=args[0];return ()
        if method=='SetTime':return ()
        raise AssertionError(method)

class SettingsTests(unittest.TestCase):
    def setUp(self):self.bus=Bus();self.backend=SystemSettingsBackend(self.bus,uid=1000,hasher=lambda p,c:'$6$opaque-hash' if p==c else (_ for _ in ()).throw(ValueError('Mismatch')))
    def mutations(self):return [c for c in self.bus.calls if c[0].startswith(('Set','Create','Delete'))]
    def test_read_only_refresh_and_current_user_first(self):
        rows=self.backend.users();self.assertTrue(rows[0]['current']);self.backend.clock();self.assertFalse(self.mutations());self.assertTrue(all(not c[2] for c in self.bus.calls))
    def test_creation_hashes_password_before_system_call_and_uses_polkit(self):
        rows=self.backend.create_user('new-user','New User','secret-value','secret-value',False);self.assertEqual(len(rows),3)
        ops=self.mutations();self.assertEqual([c[0] for c in ops],['CreateUser','SetLocked','SetPassword']);self.assertEqual(ops[-1][1],('$6$opaque-hash',''));self.assertTrue(all(c[2] for c in ops));self.assertNotIn('secret-value',repr(self.bus.calls))
    def test_creation_password_failure_leaves_account_locked_not_deleted(self):
        self.bus.fail='SetPassword'
        with self.assertRaisesRegex(ServiceError,'kept locked'):self.backend.create_user('new','New','password','password',False)
        self.assertTrue(self.bus.records[1002]['Locked']);self.assertNotIn('DeleteUser',[c[0] for c in self.bus.calls])
    def test_create_validation_prevents_service_mutation(self):
        for name in ['root','-bad','UPPER','x; id','a/b','a\n','a'*32]:
            with self.assertRaises(ValueError):self.backend.create_user(name,'Name','secret','secret',False)
        self.assertEqual(self.mutations(),[])
    def test_last_administrator_and_self_changes_are_protected(self):
        with self.assertRaisesRegex(ValueError,'administrator'):self.backend.update_user(1000,'Alice',False)
        with self.assertRaises(ValueError):self.backend.delete_user(1000)
        with self.assertRaisesRegex(ValueError,'current password'):self.backend.reset_password(1000,'new-secret','new-secret')
        self.assertEqual(self.mutations(),[])
    def test_remove_preserves_files_and_rejects_signed_in_users(self):
        self.bus.records[1001].pop('LoggedIn',None);self.bus.sessions.append(('c2',1001,'bob','seat1','/org/freedesktop/login1/session/c2'))
        with self.assertRaises(ValueError):self.backend.delete_user(1001)
        self.bus.sessions=self.bus.sessions[:1];self.backend.delete_user(1001);self.assertEqual(self.mutations()[-1],('DeleteUser',(1001,False),True,'(xb)'))
    def test_remove_fails_closed_when_active_sessions_cannot_be_checked(self):
        self.bus.fail='ListSessions'
        with self.assertRaisesRegex(ServiceError,'active sign-ins'):self.backend.delete_user(1001)
        self.assertEqual(self.mutations(),[])
    def test_profile_error_is_not_reported_as_success(self):
        self.bus.fail='SetRealName'
        with self.assertRaises(ServiceError):self.backend.update_user(1001,'Changed',False)
        self.assertEqual(self.bus.records[1001]['RealName'],'Bob')
    def test_reset_uses_opaque_hash_and_unlock_behavior(self):
        self.bus.records[1001]['Locked']=True;self.backend.reset_password(1001,'reset-secret','reset-secret');self.assertFalse(self.bus.records[1001]['Locked']);self.assertNotIn('reset-secret',repr(self.bus.calls))
    def test_timezone_membership_and_ntp_service_contract(self):
        for zone in ['../../etc/passwd','Europe/Paris\n','Not/AZone']:
            with self.assertRaises(ValueError):self.backend.set_timezone(zone)
        self.assertEqual(self.mutations(),[])
        self.backend.set_timezone('Europe/Paris');self.assertEqual(self.mutations()[-1],('SetTimezone',('Europe/Paris',True),True,'(sb)'))
        self.backend.set_ntp(False);self.assertFalse(self.backend.clock()['ntp'])
        self.bus.clock['CanNTP']=False
        with self.assertRaises(ServiceError):self.backend.set_ntp(True)
    def test_manual_clock_requires_explicit_ntp_off_and_strict_utc(self):
        with self.assertRaisesRegex(ValueError,'automatic time'):self.backend.set_time('2026-11-10 12:30')
        self.assertEqual(self.mutations(),[]);self.bus.clock['NTP']=False
        for value in ['2026-99-99 12:30','1999-01-01 12:30','2026-11-10 12:30; id','2026-11-10 12:30+01:00']:
            with self.assertRaises(ValueError):self.backend.set_time(value)
        self.backend.set_time('2026-11-10 12:30');self.assertEqual(self.mutations()[-1],('SetTime',(1794313800000000,False,True),True,'(xbb)'))
    def test_system_accounts_and_untrusted_uid_rejected(self):
        self.bus.records[1001]['SystemAccount']=True
        with self.assertRaises(ValueError):self.backend.delete_user(1001)
        for uid in [0,999,-1,True,'1001']:
            with self.assertRaises(ValueError):self.backend.delete_user(uid)
    def test_password_hashing_uses_unique_salt_and_validates_before_crypto(self):
        for password,confirm in [('short','short'),('long-enough','different'),('secret\nvalue','secret\nvalue')]:
            with self.assertRaises(ValueError):password_hash(password,confirm)
        a=password_hash('a secure test password','a secure test password');b=password_hash('a secure test password','a secure test password');self.assertTrue(a.startswith('$6$rounds=100000$'));self.assertNotEqual(a,b);self.assertNotIn('secure test password',a)

if __name__=='__main__':unittest.main()

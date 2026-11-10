import importlib.util,unittest
from datetime import datetime,timedelta,timezone
from email.utils import format_datetime
from pathlib import Path
s=importlib.util.spec_from_file_location('health',Path(__file__).resolve().parents[1]/'tools/check-update-health.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class UpdateHealthTests(unittest.TestCase):
    def setUp(self):self.now=datetime(2026,11,10,tzinfo=timezone.utc)
    def data(self,days=90,origin='Mellipi'):
        return 'Origin: '+origin+'\nLabel: '+origin+'\nSuite: noble\nCodename: noble\nArchitectures: amd64\nComponents: main\nDate: '+format_datetime(self.now-timedelta(days=1))+'\nValid-Until: '+format_datetime(self.now+timedelta(days=days))+'\n'
    def rows(self,expiry=''):
        return 'pub:u:255:22:123:123:'+str(expiry)+':x:\nfpr:::::::::'+m.FINGERPRINT+':\n'
    def test_healthy(self):self.assertTrue(m.assess(self.data(),self.rows(),'Mellipi',self.now)['ok'])
    def test_expiring_and_expired(self):
        for days in (20,0):self.assertFalse(m.assess(self.data(days),self.rows(),'Mellipi',self.now)['ok'])
    def test_legacy_identity(self):self.assertTrue(m.assess(self.data(origin='Abstract'),self.rows(),'Abstract',self.now)['ok'])
    def test_key_expiry(self):self.assertFalse(m.assess(self.data(),self.rows(int(self.now.timestamp())),'Mellipi',self.now)['ok'])
    def test_bad_identity_and_dates(self):
        for text in (self.data()+'Origin: Mellipi\n',self.data().replace('noble','jammy'),self.data().replace('Date: Mon, 09 Nov 2026','Date: Wed, 09 Dec 2026')):
            with self.assertRaises(ValueError):m.assess(text,self.rows(),'Mellipi',self.now)
    def test_wrong_key(self):
        with self.assertRaises(ValueError):m.assess(self.data(),self.rows().replace(m.FINGERPRINT,'A'*40),'Mellipi',self.now)

if __name__=='__main__':unittest.main()

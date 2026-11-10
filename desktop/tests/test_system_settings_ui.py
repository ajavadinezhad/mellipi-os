"""QML binding and password-clearing checks with inert fake controllers."""
import unittest
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot,QApplication,QQmlApplicationEngine,QUrl,QT5
if QT5:
    from PyQt5.QtQml import QQmlComponent
    from PyQt5.QtCore import QMetaObject
else:
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtCore import QMetaObject

class Orbit(QObject):
    changed=Signal()
    appearance=Property('QVariantMap',lambda s:dict(shellLayout='fold',density='compact',reducedMotion=True,corners='soft',textScale=1),notify=changed)
    compact=Property(bool,lambda s:True,notify=changed)
    economy=Property(bool,lambda s:True,notify=changed)
    themeMode=Property(str,lambda s:'dark',notify=changed)
    accentColor=Property(str,lambda s:'#b8d893',notify=changed)
    @Slot()
    def hideTooltip(self):pass

class Tools(QObject):
    changed=Signal()
    def __init__(self):super().__init__();self.requests=[]
    systemUsers=Property('QVariantList',lambda s:[dict(id=1000,name='sample',displayName='Sample User',administrator=True,locked=False,loggedIn=True,sessionsKnown=True,current=True)],notify=changed)
    systemState=Property('QVariantMap',lambda s:dict(busy=False,error='',usersAvailable=True,clockAvailable=True,timezone='Europe/Paris',ntp=True,canNtp=True,synchronized=True,zones=['America/New_York','Etc/UTC','Europe/Paris']),notify=changed)
    @Slot(str)
    def refreshSystem(self,name):pass
    @Slot(str,str,str,str,bool)
    def createSystemUser(self,name,display,password,confirmation,administrator):self.requests.append((name,display,password,confirmation,administrator))

class SystemSettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.orbit=Orbit();self.tools=Tools();self.engine=QQmlApplicationEngine();self.errors=[]
        self.engine.warnings.connect(lambda rows:self.errors.extend(r.toString() for r in rows))
        context=self.engine.rootContext();context.setContextProperty('Orbit',self.orbit);context.setContextProperty('DesktopTools',self.tools)
        self.component=QQmlComponent(self.engine,QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'native/SystemAdministrationPanel.qml')))
        self.item=self.component.create();self.assertIsNotNone(self.item,[e.toString() for e in self.component.errors()]);self.item.setProperty('width',500);self.app.processEvents()
    def tearDown(self):
        # Destroy QML while the fake context objects are still alive.
        if QT5:
            from PyQt5 import sip
            sip.delete(self.item);sip.delete(self.component);sip.delete(self.engine)
        else:
            import shiboken6
            shiboken6.delete(self.item);shiboken6.delete(self.component);shiboken6.delete(self.engine)
    def field(self,name):
        value=self.item.findChild(QObject,name);self.assertIsNotNone(value,name);return value
    def test_users_and_clock_pages_have_no_binding_errors(self):
        self.assertEqual(self.errors,[]);self.item.setProperty('section','datetime');self.app.processEvents();self.assertEqual(self.errors,[])
        self.assertEqual(self.field('systemTimezonePicker').property('count'),3)
    def test_password_fields_are_masked_and_cleared_on_submit_and_hide(self):
        self.item.setProperty('adding',True)
        for field,value in [('systemUserNewLogin','new-user'),('systemUserNewDisplay','New User'),('systemUserNewPassword','not-a-real-password'),('systemUserNewConfirm','not-a-real-password')]:self.field(field).setProperty('text',value)
        self.assertEqual(self.field('systemUserNewPassword').property('echoMode'),2)
        QMetaObject.invokeMethod(self.field('systemUserCreate'),'clicked')
        self.assertEqual(len(self.tools.requests),1)
        self.assertEqual(self.field('systemUserNewPassword').property('text'),'');self.assertEqual(self.field('systemUserNewConfirm').property('text'),'')
        self.field('systemUserResetValue').setProperty('text','another-fake-secret');self.item.setProperty('visible',False)
        self.assertEqual(self.field('systemUserResetValue').property('text'),'');self.assertEqual(self.errors,[])

if __name__=='__main__':unittest.main()

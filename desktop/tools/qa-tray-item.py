#!/usr/bin/env python3
"""Private-session fixture, never accesses or closes user applications."""
import sys
sys.path.append('/usr/lib/python3/dist-packages')
from gi.repository import Gio,GLib
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
xml='''<node><interface name="org.kde.StatusNotifierItem">
<property name="Id" type="s" access="read"/><property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/><property name="IconName" type="s" access="read"/><property name="Menu" type="o" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
</interface><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
</interface></node>'''
info=Gio.DBusNodeInfo.new_for_xml(xml)
def method(c,s,p,i,m,args,inv):
    if m=='GetLayout':
        nodes=[GLib.Variant('(ia{sv}av)',(1,{'label':GLib.Variant('s','_Open'),'enabled':GLib.Variant('b',True)},[])),GLib.Variant('(ia{sv}av)',(2,{'label':GLib.Variant('s','Quit'),'enabled':GLib.Variant('b',False)},[]))]
        inv.return_value(GLib.Variant('(u(ia{sv}av))',(1,(0,{},nodes))))
    else:
        print(m,flush=True);inv.return_value(GLib.Variant('()',()))
def prop(c,s,p,i,name):
    sig,val={'Id':('s','orbit-qa'),'Title':('s','Orbit tray fixture'),'Status':('s','Active'),'IconName':('s','utilities-terminal'),'Menu':('o','/Menu')}[name]
    return GLib.Variant(sig,val)
bus.register_object('/StatusNotifierItem',info.interfaces[0],method,prop,None)
bus.register_object('/Menu',info.interfaces[1],method,None,None)
bus.call_sync('org.kde.StatusNotifierWatcher','/StatusNotifierWatcher','org.kde.StatusNotifierWatcher','RegisterStatusNotifierItem',GLib.Variant('(s)',('/StatusNotifierItem',)),None,0,2000,None)
GLib.MainLoop().run()

"""Disposable real GTK3 XEmbed icon; refuses the physical user session."""
import os
assert os.environ.get('ORBIT_NESTED')=='1','XEmbed fixture requires a private desktop'
os.environ['GDK_BACKEND']='x11'
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
Gtk.init([])
icon=Gtk.StatusIcon.new_from_icon_name('utilities-terminal')
icon.set_title('Orbit XEmbed fixture');icon.set_tooltip_text('Orbit disposable legacy tray test');icon.set_visible(True)
icon.connect('activate',lambda *_:print('CLICK 1',flush=True))
icon.connect('popup-menu',lambda *_:print('CLICK 3',flush=True))
print('DOCKED GTK XEmbed fixture',flush=True)
GLib.timeout_add_seconds(40,lambda:(Gtk.main_quit(),False)[1])
Gtk.main()

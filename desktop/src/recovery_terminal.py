"""Minimal Xorg recovery window using the same VTE engine as Mellipi Terminal."""
import os

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Vte', '2.91')
from gi.repository import Gdk, Gtk, Pango, Vte


def main():
    window = Gtk.Window(title='Mellipi Recovery')
    window.set_default_size(800, 480)
    window.connect('destroy', Gtk.main_quit)
    terminal = Vte.Terminal()
    terminal.set_font(Pango.FontDescription('DejaVu Sans Mono 11'))
    terminal.set_scrollback_lines(2000)
    window.add(terminal)
    terminal.connect('child-exited', lambda *_: window.destroy())
    window.show_all()
    terminal.grab_focus()
    # There is no window manager in the recovery session.
    window.get_window().focus(Gdk.CURRENT_TIME)
    gi.require_version('GdkX11', '3.0')
    from gi.repository import GdkX11
    env = [f'{key}={value}' for key, value in os.environ.items() if key not in ('WINDOWID','XDG_CONFIG_HOME','XDG_DATA_HOME','GTK_THEME','GDK_BACKEND')]
    env.append('WINDOWID='+str(GdkX11.X11Window.get_xid(window.get_window())))
    def spawned(_terminal, _pid, error):
        if error:
            terminal.feed(('Could not start Mellipi Recovery: '+str(error)+'\r\n').encode())
    terminal.spawn_async(Vte.PtyFlags.DEFAULT, '/',
                         ['/usr/bin/python3','-I','/usr/lib/abstract/recovery_console.py'],
                         env, 0, None, None, -1, None, spawned)
    Gtk.main()


if __name__ == '__main__':
    main()

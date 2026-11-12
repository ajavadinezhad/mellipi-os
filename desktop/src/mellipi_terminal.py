"""Mellipi terminal window backed by the distribution's VTE library."""
import argparse
import os
import pwd
import sys
from pathlib import Path

import gi
from gi.repository import GLib

GLib.set_prgname('mellipi-terminal')

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Vte', '2.91')
from gi.repository import Gdk, GdkPixbuf, Gio, Gtk, Pango, Vte

from app_palette import HEADER_HEIGHTS, colors
from window_controls import glyph_svg
from preferences import Preferences


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--working-directory', type=Path, default=Path.home())
    parser.add_argument('-e', '--execute', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.execute == []:
        parser.error('-e requires a command')
    args.working_directory = args.working_directory.expanduser().absolute()
    if not args.working_directory.is_dir():
        parser.error('working directory is not a directory')
    return args


def shell():
    return os.environ.get('SHELL') or pwd.getpwuid(os.getuid()).pw_shell or '/bin/sh'


def rgba(value):
    result = Gdk.RGBA()
    result.parse(value)
    return result


class TerminalWindow(Gtk.Window):
    def __init__(self, args):
        super().__init__(title='Mellipi Terminal')
        self.set_default_size(860, 530)
        self.connect('destroy', lambda *_: Gtk.main_quit())
        self.connect('key-press-event', self.key_pressed)
        self.connect('delete-event', self.confirm_window_close)
        self.header = Gtk.HeaderBar(show_close_button=False, spacing=4)
        self.set_titlebar(self.header)
        new_tab = Gtk.Button.new_from_icon_name('tab-new-symbolic', Gtk.IconSize.MENU)
        new_tab.set_relief(Gtk.ReliefStyle.NONE)
        new_tab.set_tooltip_text('New tab (Ctrl+Shift+T)')
        new_tab.get_accessible().set_name('New tab')
        new_tab.connect('clicked', lambda *_: self.new_tab())
        title = Gtk.Label(label='Mellipi Terminal')
        title.set_margin_start(2)
        self.header.pack_start(title)
        self.controls = {}
        self.control_ink = '#ffffff'
        for glyph, action in (('close', self.close), ('maximize', self.toggle_maximized),
                              ('minimize', self.iconify)):
            button = Gtk.Button()
            button.get_style_context().add_class('mellipi-window-control')
            button.set_size_request(32, 28)
            button.connect('clicked', lambda _button, callback=action: callback())
            self.controls[glyph] = button
            self.header.pack_end(button)
        self.header.pack_end(new_tab)
        self.connect('window-state-event', self.window_state_changed)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_tabs(False)
        self.add(self.notebook)
        self.settings_path = Path(os.environ.get('ORBIT_SETTINGS_FILE') or
                                  Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'abstract/settings.json')
        self.preferences = Preferences(self.settings_path)
        self.last_appearance = None
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.monitor = None
        if self.settings_path.parent.is_dir():
            directory = Gio.File.new_for_path(str(self.settings_path.parent))
            self.monitor = directory.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self.monitor.connect('changed', self.settings_changed)
        self.apply_theme()
        self.add_tab(args.working_directory, args.execute or [shell()])

    def toggle_maximized(self):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def window_state_changed(self, _window, event):
        if event.changed_mask & Gdk.WindowState.MAXIMIZED:
            self.update_controls(self.control_ink, bool(event.new_window_state & Gdk.WindowState.MAXIMIZED))
        return False

    def update_controls(self, ink, maximized):
        self.control_ink = ink
        for name, button in self.controls.items():
            glyph = 'restore' if name == 'maximize' and maximized else name
            loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
            loader.write(glyph_svg(glyph, ink))
            loader.close()
            button.set_image(Gtk.Image.new_from_pixbuf(loader.get_pixbuf()))
            button.set_tooltip_text(glyph.capitalize())
            button.get_accessible().set_name(glyph.capitalize())

    def settings_changed(self, _monitor, file, other_file, _event):
        if any(item and item.get_path() == str(self.settings_path) for item in (file, other_file)):
            self.preferences = Preferences(self.settings_path)
            self.apply_theme()

    def apply_theme(self):
        palette = colors(self.preferences)
        prefs = self.preferences.values
        appearance = (palette, prefs['density'], prefs['corners'], prefs['textScale'], prefs['mode'])
        if appearance == self.last_appearance:
            return
        self.last_appearance = appearance
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', prefs['mode'] == 'dark')
        pad = {'comfortable': 8, 'compact': 5, 'extra': 3}[prefs['density']]
        radius = {'square': 0, 'soft': 4, 'rounded': 8}[prefs['corners']]
        header_height = HEADER_HEIGHTS[prefs['density']] - 1
        focus = palette['text'] if prefs['highContrast'] else palette['accent']
        self.update_controls(focus, self.is_maximized())
        self.css.load_from_data(('''
            window, notebook, notebook stack { background: %(background)s; color: %(text)s; }
            headerbar { min-height: %(header_height)dpx; padding: 0 8px; background: %(background)s;
                        color: %(text)s; border: 0; border-bottom: 1px solid %(separator)s;
                        box-shadow: none; text-shadow: none; }
            headerbar .title { font-weight: normal; }
            headerbar button, notebook tab button { min-width: 20px; min-height: 20px;
                        padding: 2px; background: transparent; color: %(focus)s;
                        border: 0; box-shadow: none; text-shadow: none; }
            headerbar button.mellipi-window-control { padding: 0; }
            headerbar button:hover, notebook tab button:hover { background: %(hover)s; }
            decoration, decoration:backdrop {
                border: 0; box-shadow: none; border-radius: %(radius)dpx;
            }
            menu, messagedialog { background: %(surface)s; color: %(text)s; }
            menuitem:hover { background: %(selected_surface)s; color: %(text)s; }
            headerbar button:focus, notebook tab button:focus {
                box-shadow: inset 0 -2px %(focus)s;
            }
            notebook tab:focus { outline-color: %(focus)s; }
            notebook header { background: %(surface)s; color: %(text)s;
                              border-bottom: 1px solid %(separator)s; }
            notebook tab { background: %(surface)s; color: %(muted)s; padding: %(padding)dpx; }
            notebook tab:checked { background: %(selected_surface)s; color: %(text)s; box-shadow: inset 0 -2px %(accent)s; }
            notebook tab button, .terminal-action-icon { color: %(focus)s; }
            .terminal-shortcut { opacity: .7; }
            .terminal-panel { border: 0; background: %(surface)s; }
        ''' % dict(palette, padding=pad, radius=radius, header_height=header_height, focus=focus)).encode())
        for i in range(self.notebook.get_n_pages()):
            self.style_terminal(self.notebook.get_nth_page(i).get_child())

    def style_terminal(self, terminal):
        prefs = self.preferences.values
        palette = colors(self.preferences)
        # Preserve ANSI color meanings with variants that contrast with the backdrop.
        normal = (
            '#222831', '#a62028', '#286139', '#805800', '#2155a0', '#823081', '#006870', '#485564'
        ) if prefs['mode'] == 'light' else (
            '#161a20', '#ea8188', '#a4c994', '#e1c780', '#93b7ef', '#cfa2de', '#86c9c9', '#d5e0e6'
        )
        bright = (
            '#526171', '#a51420', '#17662e', '#765000', '#174b9c', '#7b2380', '#005d66', '#3e4a55'
        ) if prefs['mode'] == 'light' else (
            '#87919c', '#ffa6ad', '#bde8ad', '#ffe1a1', '#b3d3ff', '#e5b8f1', '#a5e4e4', '#ffffff'
        )
        terminal.set_colors(rgba(palette['text']), rgba(palette['surface']),
                            [rgba(value) for value in (*normal, *bright)])
        terminal.set_color_cursor(rgba(palette['accent']))
        terminal.set_color_cursor_foreground(rgba(palette['accent_text']))
        terminal.set_color_highlight(rgba(palette['accent']))
        terminal.set_color_highlight_foreground(rgba(palette['accent_text']))
        font = Pango.FontDescription('Monospace')
        font.set_size(round(11 * prefs['textScale'] * Pango.SCALE))
        terminal.set_font(font)
        pad = {'comfortable': 8, 'compact': 5, 'extra': 3}[prefs['density']]
        terminal.set_margin_start(pad)
        terminal.set_margin_end(pad)
        terminal.set_margin_top(pad)
        terminal.set_margin_bottom(pad)

    def current_terminal(self):
        page = self.notebook.get_nth_page(self.notebook.get_current_page())
        return page.get_child() if page is not None else None

    def add_tab(self, directory, argv):
        terminal = Vte.Terminal()
        terminal.launch_directory = directory
        terminal.set_scrollback_lines(5000)
        self.style_terminal(terminal)
        page = Gtk.ScrolledWindow()
        page.get_style_context().add_class('terminal-panel')
        page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page.add(terminal)
        terminal.connect('button-press-event', self.context_menu, page)
        tab = Gtk.Box(spacing=6)
        label = Gtk.Label()
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        label.set_max_width_chars(24)
        close = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text('Close tab (Ctrl+Shift+W)')
        close.connect('clicked', lambda *_: self.confirm_close(page))
        def update_tab(*_):
            current = self.tab_directory(terminal)
            name = current.name or '/'
            label.set_text(name)
            label.set_tooltip_text(str(current))
            close.get_accessible().set_name(f'Close {name} tab')

        terminal.connect('notify::current-directory-uri', update_tab)
        update_tab()
        tab.pack_start(label, True, True, 0)
        tab.pack_start(close, False, False, 0)
        terminal.connect('child-exited', lambda *_: self.remove_tab(page))
        index = self.notebook.append_page(page, tab)
        tab.show_all()
        page.show_all()
        self.notebook.set_show_tabs(self.notebook.get_n_pages() > 1)
        self.notebook.set_current_page(index)
        terminal.grab_focus()
        terminal.spawn_async(Vte.PtyFlags.DEFAULT, str(directory), argv, None,
                             GLib.SpawnFlags.SEARCH_PATH, None, None, -1, None,
                             self.spawned, page)

    def spawned(self, _terminal, _pid, error, page):
        if error:
            self.alert('Could not start terminal', error.message)
            self.remove_tab(page)

    def remove_tab(self, page):
        index = self.notebook.page_num(page)
        if index == -1:
            return
        self.notebook.remove_page(index)
        page.destroy()
        count = self.notebook.get_n_pages()
        self.notebook.set_show_tabs(count > 1)
        if not count:
            self.destroy()
        else:
            self.current_terminal().grab_focus()

    def alert(self, title, message, buttons=Gtk.ButtonsType.CLOSE):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, buttons=buttons, text=title)
        dialog.format_secondary_text(message)
        response = dialog.run()
        dialog.destroy()
        return response

    def confirm_window_close(self, _window, _event):
        count = self.notebook.get_n_pages()
        if not count:
            return False
        message = ('This will stop the program running in this tab.' if count == 1
                   else 'This will close all tabs and their running programs.')
        return self.alert('Close terminal window?', message,
                          Gtk.ButtonsType.OK_CANCEL) != Gtk.ResponseType.OK

    def confirm_close(self, page):
        if self.alert('Close terminal tab?', 'The program running in this tab will lose its terminal.',
                      Gtk.ButtonsType.OK_CANCEL) == Gtk.ResponseType.OK:
            self.remove_tab(page)

    @staticmethod
    def tab_directory(terminal):
        if terminal is None:
            return Path.home()
        uri = terminal.get_current_directory_uri()
        if uri:
            local = Gio.File.new_for_uri(uri).get_path()
            if local and Path(local).is_dir():
                return Path(local)
        if terminal.launch_directory.is_dir():
            return terminal.launch_directory
        return Path.home()

    def new_tab(self):
        self.add_tab(self.tab_directory(self.current_terminal()), [shell()])

    def key_pressed(self, _window, event):
        modifiers = event.state & Gtk.accelerator_get_default_mod_mask()
        if modifiers != Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK:
            return False
        terminal = self.current_terminal()
        if not terminal:
            return False
        key = Gdk.keyval_to_lower(event.keyval)
        if key == Gdk.KEY_c:
            terminal.copy_clipboard_format(Vte.Format.TEXT)
        elif key == Gdk.KEY_v:
            terminal.paste_clipboard()
        elif key == Gdk.KEY_t:
            self.new_tab()
        elif key == Gdk.KEY_w:
            self.confirm_close(self.notebook.get_nth_page(self.notebook.get_current_page()))
        else:
            return False
        return True

    def context_menu(self, terminal, event, page):
        if event.button != 3 or event.state & Gdk.ModifierType.SHIFT_MASK:
            return False
        menu = Gtk.Menu()
        actions = (
            ('Copy', 'edit-copy-symbolic', 'Ctrl+Shift+C', lambda: terminal.copy_clipboard_format(Vte.Format.TEXT), terminal.get_has_selection()),
            ('Paste', 'edit-paste-symbolic', 'Ctrl+Shift+V', terminal.paste_clipboard, True),
            ('New tab', 'tab-new-symbolic', 'Ctrl+Shift+T', self.new_tab, True),
            ('Close tab', 'window-close-symbolic', 'Ctrl+Shift+W', lambda: self.confirm_close(page), True),
        )
        for label, icon, shortcut, callback, enabled in actions:
            item = Gtk.MenuItem()
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
            image.get_style_context().add_class('terminal-action-icon')
            row.pack_start(image, False, False, 0)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            accelerator = Gtk.Label(label=shortcut, xalign=1)
            accelerator.get_style_context().add_class('terminal-shortcut')
            row.pack_end(accelerator, False, False, 0)
            item.add(row)
            item.get_accessible().set_name(label)
            item.get_accessible().set_description(shortcut)
            item.set_sensitive(enabled)
            item.connect('activate', lambda _item, fn=callback: fn())
            menu.append(item)
        menu.attach_to_widget(terminal, None)
        menu.connect('selection-done', lambda item: item.destroy())
        menu.show_all()
        menu.popup_at_pointer(event)
        return True


def main():
    args = arguments(sys.argv[1:])
    GLib.set_application_name('Mellipi Terminal')
    window = TerminalWindow(args)
    window.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()

"""Mellipi terminal window backed by the distribution's VTE library."""
import argparse
import os
import pwd
import re
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

from app_palette import HEADER_HEIGHTS, colors, identity_appearance
from window_controls import glyph_svg
from preferences import Preferences


# Flags from pcre2.h used by Vte.Regex (VTE expects multiline search).
_PCRE2_CASELESS = 0x00000008
_PCRE2_MULTILINE = 0x00000400
_PCRE2_UTF = 0x00080000


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
        self.new_tab_button = new_tab
        new_tab.set_relief(Gtk.ReliefStyle.NONE)
        new_tab.set_tooltip_text('New tab (Ctrl+Shift+T)')
        new_tab.get_accessible().set_name('New tab')
        new_tab.connect('clicked', lambda *_: self.new_tab())
        self.identity_badge = Gtk.Box()
        self.identity_badge.set_size_request(22, 22)
        self.identity_badge.set_valign(Gtk.Align.CENTER)
        self.identity_badge.get_style_context().add_class('app-identity')
        self.identity_image = None
        self.header.pack_start(self.identity_badge)
        title = Gtk.Label(label='Mellipi Terminal')
        title.get_style_context().add_class('title')
        title.set_ellipsize(Pango.EllipsizeMode.END)
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
        self.find_button = Gtk.Button()
        self.find_button.set_relief(Gtk.ReliefStyle.NONE)
        self.find_button.set_tooltip_text('Find in this tab (Ctrl+Shift+F)')
        self.find_button.get_accessible().set_name('Find in this tab')
        self.find_button.connect('clicked', lambda *_: self.show_search())
        self.header.pack_end(self.find_button)
        self.connect('window-state-event', self.window_state_changed)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_tabs(False)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(content)
        self._search_terminal = None
        self._search_matched = False
        self.search_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.NONE)
        self.search_bar = Gtk.Grid(column_spacing=6, row_spacing=4)
        self.search_bar.get_style_context().add_class('terminal-search')
        self.search_revealer.add(self.search_bar)
        self.search_entry = Gtk.SearchEntry(placeholder_text='Find in tab', max_length=256)
        self.search_entry.set_width_chars(7)
        self.search_entry.set_max_width_chars(22)
        self.search_entry.get_accessible().set_name('Find in this terminal tab')
        self.search_entry.connect('changed', self.update_search)
        self.search_entry.connect('key-press-event', self.search_key_pressed)
        self.search_entry.set_hexpand(True)
        self.search_bar.attach(self.search_entry, 0, 0, 1, 1)
        search_options = Gtk.Box(spacing=8)
        self.search_case = Gtk.CheckButton(label='Match case')
        self.search_case.connect('toggled', self.update_search)
        search_options.pack_start(self.search_case, False, False, 0)
        self.search_status = Gtk.Label(xalign=0)
        self.search_status.get_style_context().add_class('terminal-search-status')
        self.search_status.get_accessible().set_name('Search status')
        self.search_status.set_ellipsize(Pango.EllipsizeMode.END)
        search_options.pack_start(self.search_status, True, True, 0)
        self.search_bar.attach(search_options, 0, 1, 4, 1)
        self.search_buttons = {}
        for column, (icon, title, callback) in enumerate((
            ('go-up', 'Previous match', lambda: self.find_match(False)),
            ('go-down', 'Next match', lambda: self.find_match(True)),
            ('close', 'Close find', self.hide_search),
        ), start=1):
            button = Gtk.Button()
            button.set_tooltip_text(title)
            button.get_accessible().set_name(title)
            button.connect('clicked', lambda _button, action=callback: action())
            self.search_bar.attach(button, column, 0, 1, 1)
            self.search_buttons[icon] = button
        content.pack_start(self.search_revealer, False, False, 0)
        content.pack_start(self.notebook, True, True, 0)
        self.notebook.connect('switch-page', self.search_switched_tab)
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
        self.connect('notify::scale-factor', lambda *_: self.apply_theme())
        self.apply_theme()
        self.update_search()
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
            button.set_image(self.svg_image(glyph_svg(
                glyph, ink, self.preferences.values["themePreset"] == "cyberpunk")))
            button.set_tooltip_text(glyph.capitalize())
            button.get_accessible().set_name(glyph.capitalize())

    def settings_changed(self, _monitor, file, other_file, _event):
        if any(item and item.get_path() == str(self.settings_path) for item in (file, other_file)):
            self.preferences = Preferences(self.settings_path)
            self.apply_theme()

    def apply_theme(self):
        palette = colors(self.preferences)
        prefs = self.preferences.values
        appearance = (palette, prefs['density'], prefs['corners'], prefs['textScale'], prefs['mode'], prefs['themePreset'], self.get_scale_factor())
        if appearance == self.last_appearance:
            return
        self.last_appearance = appearance
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', prefs['mode'] == 'dark')
        pad = {'comfortable': 8, 'compact': 6, 'extra': 4}[prefs['density']]
        radius = {'square': 0, 'soft': 4, 'rounded': 8}[prefs['corners']]
        header_height = HEADER_HEIGHTS[prefs['density']] - 1
        self.update_controls(palette['accent_ink'], self.is_maximized())
        from mellipi_icons import svg
        glyph, ink, identity_bg = identity_appearance('Mellipi Terminal', palette['background'])
        if self.identity_image:
            self.identity_badge.remove(self.identity_image)
        self.identity_image = self.svg_image(svg(glyph, ink, size=16))
        self.identity_badge.pack_start(self.identity_image, True, True, 0)
        self.identity_image.show()
        self.new_tab_button.set_image(self.action_image('tab-new'))
        self.find_button.set_image(self.action_image('search'))
        for icon, button in self.search_buttons.items():
            button.set_image(self.action_image(icon))
        for index in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(index)
            close = getattr(page, 'mellipi_close_button', None)
            if close is not None:
                close.set_image(self.action_image('close'))
        self.css.load_from_data(('''
            window, notebook, notebook stack { background: %(background)s; color: %(text)s; }
            headerbar { min-height: %(header_height)dpx; padding: 0 8px; background: %(background)s;
                        color: %(text)s; border: 0; border-bottom: 1px solid %(separator)s;
                        box-shadow: none; text-shadow: none; }
            headerbar .app-identity { background: %(identity_bg)s; border-radius: %(radius)dpx; }
            headerbar .title { font-weight: 600; font-size: %(label_size)dpx; }
            headerbar button, notebook tab button { min-width: 20px; min-height: 20px;
                        padding: 2px; background: transparent; color: %(accent_ink)s;
                        border: 0; box-shadow: none; text-shadow: none; }
            headerbar button.mellipi-window-control { padding: 0; }
            headerbar button:hover, notebook tab button:hover { background: %(hover)s; }
            decoration, decoration:backdrop {
                border: 0; box-shadow: none; border-radius: %(radius)dpx;
            }
            menu, messagedialog { background: %(surface)s; color: %(text)s; }
            messagedialog .title { color: %(accent_ink)s; }
            messagedialog button {
                background: %(selected_surface)s; color: %(accent_ink)s;
                border-color: transparent; box-shadow: none; text-shadow: none;
            }
            messagedialog button.suggested-action {
                background: %(accent)s; color: %(accent_text)s;
            }
            messagedialog button:hover,
            messagedialog button:focus { border-color: %(focus)s; }
            menuitem:hover, menuitem:focus, menuitem:selected { background: %(selected_surface)s; color: %(text)s; }
            headerbar button:focus, notebook tab button:focus {
                box-shadow: inset 0 -2px %(focus)s;
            }
            notebook tab:focus { outline-color: %(focus)s; }
            notebook header { background: %(surface)s; color: %(text)s;
                              border-bottom: 1px solid %(separator)s; }
            notebook tab { background: %(surface)s; color: %(muted)s; padding: %(padding)dpx;
                           font-size: %(label_size)dpx; }
            notebook tab:checked { background: %(selected_surface)s; color: %(text)s; box-shadow: inset 0 -2px %(focus)s; }
            notebook tab button, .terminal-action-icon { color: %(accent_ink)s; }
            .terminal-shortcut { opacity: .7; }
            .terminal-panel { border: 0; background: %(surface)s; }
            .terminal-search { background: %(background)s; color: %(text)s; padding: %(padding)dpx 8px;
                               font-size: %(label_size)dpx;
                               border-bottom: 1px solid %(separator)s; }
            .terminal-search-status, .terminal-shortcut { color: %(muted)s; }
            .terminal-search entry, .terminal-search button {
                min-height: %(search_height)dpx; padding: 0 6px;
                background: %(surface)s; color: %(text)s; border: 1px solid %(search_border)s;
                border-radius: %(radius)dpx; box-shadow: none;
            }
            .terminal-search button { min-width: %(search_height)dpx; padding: 0; }
            .terminal-search entry:focus, .terminal-search button:focus { border-color: %(focus)s; }
            .terminal-search button:hover { background: %(hover)s; }
            .terminal-search entry selection { background: %(accent)s; color: %(accent_text)s; }
        ''' % dict(palette, padding=pad, radius=radius, identity_bg=identity_bg, header_height=header_height,
                   label_size=round(14*prefs['textScale']), search_height=max(28, round(22*prefs['textScale'])),
                   search_border=palette['control_border'])).encode())
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
        terminal.set_color_cursor(rgba(palette['focus']))
        terminal.set_color_cursor_foreground(rgba(palette['focus_text']))
        terminal.set_color_highlight(rgba(palette['accent']))
        terminal.set_color_highlight_foreground(rgba(palette['accent_text']))
        font = Pango.FontDescription('Monospace')
        font.set_size(round(11 * prefs['textScale'] * Pango.SCALE))
        terminal.set_font(font)
        pad = {'comfortable': 8, 'compact': 6, 'extra': 4}[prefs['density']]
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
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        label.set_max_width_chars(24)
        close = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)
        page.mellipi_close_button = close
        close.set_image(self.action_image('close'))
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
        if not self.search_revealer.get_reveal_child():
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
        if page.get_child() is self._search_terminal:
            self._search_terminal.search_set_regex(None, 0)
            self._search_terminal = None
        self.notebook.remove_page(index)
        page.destroy()
        count = self.notebook.get_n_pages()
        self.notebook.set_show_tabs(count > 1)
        if not count:
            self.destroy()
        elif not self.search_revealer.get_reveal_child():
            self.current_terminal().grab_focus()

    def alert(self, title, message, buttons=Gtk.ButtonsType.CLOSE, *, confirm_label=None):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, buttons=buttons,
                                   text=title, use_header_bar=False)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.set_titlebar(Gtk.HeaderBar(title='Mellipi Terminal', show_close_button=False))
        primary = dialog.get_widget_for_response(
            Gtk.ResponseType.OK if buttons == Gtk.ButtonsType.OK_CANCEL else Gtk.ResponseType.CLOSE)
        if primary is not None:
            primary.get_style_context().add_class('suggested-action')
            if confirm_label:
                primary.set_label(confirm_label)
        safe_response = Gtk.ResponseType.CANCEL if buttons == Gtk.ButtonsType.OK_CANCEL else Gtk.ResponseType.CLOSE
        dialog.set_default_response(safe_response)
        dialog.format_secondary_text(message)
        safe_button = dialog.get_widget_for_response(safe_response)
        if safe_button is not None:
            safe_button.grab_focus()
        try:
            return dialog.run()
        finally:
            dialog.destroy()

    def confirm_window_close(self, _window, _event):
        count = self.notebook.get_n_pages()
        if not count:
            return False
        message = ('This will stop the program running in this tab.' if count == 1
                   else 'This will close all tabs and their running programs.')
        return self.alert('Close terminal window?', message,
                          Gtk.ButtonsType.OK_CANCEL, confirm_label='Close Window') != Gtk.ResponseType.OK

    def confirm_close(self, page):
        if self.alert('Close terminal tab?', 'The program running in this tab will lose its terminal.',
                      Gtk.ButtonsType.OK_CANCEL, confirm_label='Close Tab') == Gtk.ResponseType.OK:
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

    def show_search(self):
        self.search_revealer.set_reveal_child(True)
        self.update_search()
        self.search_entry.grab_focus()
        self.search_entry.select_region(0, -1)

    def hide_search(self):
        self.search_revealer.set_reveal_child(False)
        self.update_search()
        terminal = self.current_terminal()
        if terminal is not None:
            terminal.grab_focus()

    def search_switched_tab(self, _notebook, page, _index):
        # Gtk.Notebook may emit before its current index has changed.
        self.update_search(terminal=page.get_child())

    def update_search(self, *_signal, terminal=None):
        if self._search_terminal is not None:
            self._search_terminal.search_set_regex(None, 0)
        self._search_terminal = None
        self._search_matched = False
        query = self.search_entry.get_text()
        terminal = terminal if terminal is not None else self.current_terminal()
        ready = terminal is not None and bool(query) and self.search_revealer.get_reveal_child()
        self.search_status.set_text('')
        if ready:
            flags = _PCRE2_UTF | _PCRE2_MULTILINE
            if not self.search_case.get_active():
                flags |= _PCRE2_CASELESS
            # Quote metacharacters. Pasting a regex never executes it as one.
            try:
                regex = Vte.Regex.new_for_search(re.escape(query), -1, flags)
            except GLib.Error:
                self.search_status.set_text('Invalid text')
                ready = False
            else:
                self._search_terminal = terminal
                terminal.search_set_regex(regex, 0)
                terminal.search_set_wrap_around(True)
                self.find_match(False)
        for icon in ('go-up', 'go-down'):
            self.search_buttons[icon].set_sensitive(ready)

    def find_match(self, forward):
        terminal = self._search_terminal
        if terminal is None:
            return False
        search = terminal.search_find_next if forward else terminal.search_find_previous
        found = search()
        if not found and self._search_matched:
            # VTE skips the current selection even when it is the only match.
            # A failed step clears it; retry once to wrap back onto that match.
            found = search()
        self._search_matched = found
        self.search_status.set_text('' if found else 'No match')
        return found

    def search_key_pressed(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_search()
        elif event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.find_match(not bool(event.state & Gdk.ModifierType.SHIFT_MASK))
        else:
            return False
        return True

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
        elif key == Gdk.KEY_f:
            self.show_search()
        elif key == Gdk.KEY_t:
            self.new_tab()
        elif key == Gdk.KEY_w:
            self.confirm_close(self.notebook.get_nth_page(self.notebook.get_current_page()))
        else:
            return False
        return True

    def action_image(self, name):
        from mellipi_icons import svg
        ink = colors(self.preferences)['accent_ink']
        data = svg(name, ink)
        if not data:
            return Gtk.Image.new_from_icon_name(name, Gtk.IconSize.MENU)
        return self.svg_image(data)

    def svg_image(self, data):
        self_scale = self.get_scale_factor()
        loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
        loader.set_size(16 * self_scale, 16 * self_scale)
        loader.write(data)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if self_scale > 1:
            surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self_scale, self.get_window())
            return Gtk.Image.new_from_surface(surface)
        return Gtk.Image.new_from_pixbuf(pixbuf)

    def context_menu(self, terminal, event, page):
        if event.button != 3 or event.state & Gdk.ModifierType.SHIFT_MASK:
            return False
        menu = Gtk.Menu()
        actions = (
            ('Copy', 'edit-copy-symbolic', 'Ctrl+Shift+C', lambda: terminal.copy_clipboard_format(Vte.Format.TEXT), terminal.get_has_selection()),
            ('Paste', 'edit-paste-symbolic', 'Ctrl+Shift+V', terminal.paste_clipboard, True),
            ('Find in tab', 'edit-find-symbolic', 'Ctrl+Shift+F', self.show_search, True),
            ('New tab', 'tab-new-symbolic', 'Ctrl+Shift+T', self.new_tab, True),
            ('Close tab', 'window-close-symbolic', 'Ctrl+Shift+W', lambda: self.confirm_close(page), True),
        )
        for label, icon, shortcut, callback, enabled in actions:
            item = Gtk.MenuItem()
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            image = self.action_image(icon)
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

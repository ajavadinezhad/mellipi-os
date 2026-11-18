"""Session-local Mellipi dialog; polkit and PAM perform authentication."""
from dataclasses import dataclass
import os
import pwd
import sys
from locale import LC_MESSAGES, setlocale

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Polkit', '1.0')
gi.require_version('PolkitAgent', '1.0')
from gi.repository import Gio, GLib, Gtk, Pango, Polkit, PolkitAgent

from app_palette import colors
from installed_launcher import user_environment
from native_compositor import NativeCompositor
from preferences import Preferences


@dataclass
class Request:
    task: Gio.Task
    message: str
    cookie: str
    identities: list
    cancellable: Gio.Cancellable | None
    cancel_id: int = 0


def account_name(identity):
    if isinstance(identity, Polkit.UnixUser):
        try:
            return pwd.getpwuid(identity.get_uid()).pw_name
        except KeyError:
            pass
    return identity.to_string()


class AuthorizationDialog(Gtk.Dialog):
    def __init__(self, request, cancel, choose, submit):
        super().__init__(title='Administrator permission', modal=True)
        self.set_name('mellipi-authorization')
        titlebar = Gtk.HeaderBar(title='Administrator permission', show_close_button=False)
        self.set_titlebar(titlebar)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_default_size(420, -1)
        self.add_button('Cancel', Gtk.ResponseType.CANCEL)
        self.authenticate = self.add_button('Authenticate', Gtk.ResponseType.OK)
        self.authenticate.get_style_context().add_class('mellipi-primary')
        self.authenticate.set_sensitive(False)
        self.set_default_response(Gtk.ResponseType.OK)
        body = self.get_content_area()
        body.set_border_width(16)
        body.set_spacing(10)
        description = Gtk.Label(label=request.message or 'This action requires administrator permission.',
                                xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                                max_width_chars=50, selectable=True)
        description.get_accessible().set_name('Requested administrator action')
        detail = Gtk.ScrolledWindow()
        detail.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        detail.set_propagate_natural_height(True)
        display = self.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        available = monitor.get_workarea().height if monitor else 480
        detail.set_max_content_height(min(168, max(54, available // 4)))
        detail.add(description)
        body.pack_start(detail, False, False, 0)
        accounts = Gtk.ComboBoxText()
        for identity in request.identities:
            accounts.append_text(account_name(identity))
        accounts.set_active(0)
        if len(request.identities) == 1:
            account = Gtk.Label(label='Account: ' + account_name(request.identities[0]), xalign=0)
        else:
            account = accounts
            accounts.get_accessible().set_name('Administrator account')
        body.pack_start(account, False, False, 0)
        self.prompt = Gtk.Label(label='Password', xalign=0)
        body.pack_start(self.prompt, False, False, 0)
        self.entry = Gtk.Entry(visibility=False, activates_default=True, max_length=4096)
        self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.prompt.set_mnemonic_widget(self.entry)
        self.entry.get_accessible().set_name('Password')
        self.entry.set_sensitive(False)
        body.pack_start(self.entry, False, False, 0)
        self.feedback = Gtk.Label(xalign=0, wrap=True, max_width_chars=50, no_show_all=True)
        body.pack_start(self.feedback, False, False, 0)

        self.connect('response', lambda _dialog, response:
                     submit() if response == Gtk.ResponseType.OK else cancel())
        accounts.connect('changed', lambda combo: choose(combo.get_active()))
        preferences = Preferences(user_environment()['ORBIT_SETTINGS_FILE'])
        palette = colors(preferences)
        palette.setdefault('control_border', palette['border'])
        palette.setdefault('focus', palette['accent'])
        provider = Gtk.CssProvider()
        scale = preferences.values['textScale']
        provider.load_from_data((
            '#mellipi-authorization { background-color: %(background)s; color: %(text)s; }'
            '#mellipi-authorization headerbar { background-image: none;'
            ' background-color: %(chrome)s; color: %(chrome_text)s; border: none; box-shadow: none; }'
            '#mellipi-authorization label { color: %(text)s; }'
            '#mellipi-authorization headerbar label { color: %(chrome_text)s; }'
            '#mellipi-authorization entry, #mellipi-authorization button {'
            ' background-image: none; background-color: %(surface)s; color: %(text)s;'
            ' border: 1px solid %(control_border)s; border-radius: 7px; }'
            '#mellipi-authorization entry:focus, #mellipi-authorization button:focus {'
            ' border-color: %(focus)s; }'
            '#mellipi-authorization button.mellipi-primary {'
            ' background-color: %(accent)s; color: %(accent_text)s; }'
            '#mellipi-authorization button.mellipi-primary label { color: %(accent_text)s; }'
            '#mellipi-authorization button.mellipi-primary:disabled { background-color: %(surface)s; }'
            '#mellipi-authorization button.mellipi-primary:disabled label { color: %(muted)s; }'
        ).encode() % {key.encode(): value.encode() for key, value in palette.items()})
        # Loaded only into this one-purpose process.
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if scale != 1.0:
            font_style = Gtk.CssProvider()
            font_style.load_from_data(f'#mellipi-authorization {{ font-size: {round(scale * 13)}px; }}'.encode())
            self.get_style_context().add_provider(font_style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.provider = provider
        self.show_all()

    def set_feedback(self, message):
        self.feedback.set_text(message[:240])
        self.feedback.set_visible(bool(message))

    def ask(self, message, echo):
        label = message.strip().rstrip(':') or ('Response' if echo else 'Password')
        self.prompt.set_text(label)
        self.entry.get_accessible().set_name(label)
        self.entry.set_visibility(echo)
        self.entry.set_sensitive(True)
        self.authenticate.set_sensitive(True)
        self.entry.grab_focus()

    def set_waiting(self):
        self.entry.set_text('')
        self.entry.set_sensitive(False)
        self.authenticate.set_sensitive(False)

    def dispose(self):
        self.entry.set_text('')
        Gtk.StyleContext.remove_provider_for_screen(self.get_screen(), self.provider)
        self.destroy()


class Listener(PolkitAgent.Listener):
    def __init__(self, *, dialog_factory=AuthorizationDialog, session_factory=PolkitAgent.Session.new,
                 can_prompt=None):
        super().__init__()
        self.dialog_factory = dialog_factory
        self.session_factory = session_factory
        self.can_prompt = can_prompt if can_prompt is not None else self.unlocked
        self.current = self.dialog = self.session = None
        self.attempts = self.account = 0

    @staticmethod
    def unlocked():
        try:
            return NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']).status().get('locked') is False
        except (KeyError, OSError, ValueError, RuntimeError):
            return False

    @staticmethod
    def deny(task, error=Polkit.Error.CANCELLED):
        task.return_error(GLib.Error.new_literal(Polkit.error_quark(),
                                                'Authentication did not complete', error))

    def do_initiate_authentication(self, _action, message, _icon, _details, cookie, identities,
                                   cancellable, callback, callback_data):
        task = Gio.Task.new(self, cancellable, callback, callback_data)
        self.begin(task, message, cookie, identities, cancellable)

    def begin(self, task, message, cookie, identities, cancellable=None):
        if task.return_error_if_cancelled():
            return
        if self.current or not identities or not self.can_prompt():
            self.deny(task, Polkit.Error.NOT_AUTHORIZED)
            return
        request = Request(task, message, cookie, identities, cancellable)
        self.current = request
        self.attempts = 0
        if cancellable:
            request.cancel_id = cancellable.connect(lambda *_: GLib.idle_add(self.cancel_request, request))
        try:
            self.dialog = self.dialog_factory(request, self.cancel, self.choose, self.submit)
            self.choose(0)
        except Exception:
            print('Mellipi authorization: could not open the prompt', file=sys.stderr)
            self.finish(False)

    def do_initiate_authentication_finish(self, result):
        return result.propagate_boolean()

    def cancel_request(self, request):
        if self.current is request:
            self.cancel()
        return GLib.SOURCE_REMOVE

    def cancel(self):
        self.finish(False)

    def choose(self, index):
        request = self.current
        if request is None or not 0 <= index < len(request.identities):
            return
        old, self.session = self.session, None
        if old is not None:
            old.cancel()
        self.account = index
        self.dialog.set_waiting()
        session = self.session_factory(request.identities[index], request.cookie)
        self.session = session
        session.connect('request', self.on_prompt)
        session.connect('show-info', self.on_feedback)
        session.connect('show-error', self.on_feedback)
        session.connect('completed', self.on_completed)
        session.initiate()

    def on_prompt(self, session, message, echo):
        if self.session is session:
            self.dialog.ask(message, echo)

    def on_feedback(self, session, message):
        if self.session is session:
            self.dialog.set_feedback(message)

    def submit(self):
        if not self.session or not self.dialog.entry.get_sensitive():
            return
        if not self.can_prompt():
            self.cancel()
            return
        response = self.dialog.entry.get_text()
        self.dialog.set_waiting()
        self.session.response(response)

    def on_completed(self, session, authorized):
        if self.session is not session:
            return
        self.session = None
        if not authorized:
            self.attempts += 1
            if self.attempts < 3 and self.can_prompt():
                self.dialog.set_feedback('Authentication failed. Try again.')
                self.choose(self.account)
                return
        self.finish(authorized, Polkit.Error.NOT_AUTHORIZED)

    def finish(self, authorized, error=Polkit.Error.CANCELLED):
        request, self.current = self.current, None
        if request is None:
            return
        if request.cancel_id:
            request.cancellable.disconnect(request.cancel_id)
        session, self.session = self.session, None
        if session is not None:
            session.cancel()
        if self.dialog:
            self.dialog.dispose()
            self.dialog = None
        if not request.task.return_error_if_cancelled():
            if authorized:
                request.task.return_boolean(True)
            else:
                self.deny(request.task, error)


AUTHORITY = 'org.freedesktop.PolicyKit1'
AGENT_INTERFACE = AUTHORITY + '.AuthenticationAgent'
AGENT_PATH = '/org/mellipi/PolicyKit/AuthenticationAgent'
AGENT_XML = """
<node><interface name="org.freedesktop.PolicyKit1.AuthenticationAgent">
<method name="BeginAuthentication">
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{ss}" direction="in"/><arg type="s" direction="in"/><arg type="a(sa{sv})" direction="in"/>
</method>
<method name="CancelAuthentication"><arg type="s" direction="in"/></method>
</interface></node>
"""


class Invocation:
    """Complete the request on the same system bus; never send response text."""
    def __init__(self, invocation):
        self.invocation = invocation

    def return_error_if_cancelled(self):
        return False

    def return_error(self, error):
        suffix = 'Cancelled' if error.matches(Polkit.error_quark(), Polkit.Error.CANCELLED) else 'NotAuthorized'
        self.invocation.return_dbus_error(AUTHORITY + '.Error.' + suffix, 'Authentication did not complete')

    def return_boolean(self, authorized):
        if authorized:
            self.invocation.return_value(None)


class Agent:
    """Bind incoming method calls to the verified unique owner of polkitd."""
    def __init__(self, subject, listener):
        self.listener = listener
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.authority = Gio.DBusProxy.new_sync(
            self.bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None, AUTHORITY,
            '/org/freedesktop/PolicyKit1/Authority', AUTHORITY + '.Authority', None)
        self.subject = ('unix-session', {'session-id': GLib.Variant('s', subject.get_session_id())})
        self.interface = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
        self.export = self.bus.register_object(AGENT_PATH, self.interface.interfaces[0], self.dispatch, None, None)
        if not self.export:
            raise RuntimeError('Could not export the authorization endpoint')
        self.register()
        self.authority.connect('notify::g-name-owner', self.owner_changed)

    def register(self):
        if not self.authority.get_name_owner():
            raise RuntimeError('PolicyKit authority is unavailable')
        self.authority.call_sync('RegisterAuthenticationAgent',
                                 GLib.Variant('((sa{sv})ss)', (self.subject, setlocale(LC_MESSAGES), AGENT_PATH)),
                                 Gio.DBusCallFlags.NONE, 3000, None)

    def owner_changed(self, *_):
        self.listener.cancel()
        if self.authority.get_name_owner():
            try:
                self.register()
            except (GLib.Error, RuntimeError):
                Gtk.main_quit()

    def dispatch(self, bus, sender, path, interface, method, parameters, invocation):
        if not sender or sender != self.authority.get_name_owner():
            invocation.return_dbus_error('org.freedesktop.DBus.Error.AccessDenied', 'Only polkitd can authorize')
            return
        if method == 'BeginAuthentication':
            _action, message, _icon, _details, cookie, identities = parameters.unpack()
            users = [Polkit.UnixUser.new(details['uid']) for kind, details in identities
                     if kind == 'unix-user' and type(details.get('uid')) is int]
            self.listener.begin(Invocation(invocation), message, cookie, users)
        elif method == 'CancelAuthentication':
            if self.listener.current and self.listener.current.cookie == parameters.unpack()[0]:
                self.listener.cancel()
            invocation.return_value(None)


def main():
    if os.getuid() == 0 or os.environ.get('ORBIT_NESTED') or not os.environ.get('ORBIT_NATIVE_CONTROL'):
        return 1
    GLib.set_prgname('mellipi-auth-agent')
    ok, _args = Gtk.init_check()
    if not ok:
        return 1
    try:
        listener = Listener()
        subject = Polkit.UnixSession.new_for_process_sync(os.getpid(), None)
        if subject is None:
            return 1
        agent = Agent(subject, listener)
    except (GLib.Error, RuntimeError, ValueError):
        print('Mellipi authorization: agent registration unavailable', file=sys.stderr)
        return 1
    Gtk.main()
    agent.listener.cancel()
    return 1


if __name__ == '__main__':
    sys.exit(main())

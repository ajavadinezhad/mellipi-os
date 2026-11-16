"""Exercise the agent listener without passwords, PolicyKit D-Bus or PAM."""
import unittest
from unittest.mock import Mock

from mellipi_permission_agent import Agent, Gio, GLib, Listener, Polkit


class FakeDialog:
    def __init__(self, request, cancel, choose, submit):
        self.entry = self
        self.secret = ''
        self.waiting = self.closed = False

    def ask(self, prompt, echo):
        self.prompt = prompt, echo
        self.waiting = False

    def set_waiting(self):
        self.secret = ''
        self.waiting = True

    def get_sensitive(self):
        return not self.waiting

    def get_text(self):
        return self.secret

    def set_feedback(self, message):
        self.feedback = message

    def dispose(self):
        self.secret = ''
        self.closed = True


class FakeSession:
    def __init__(self, identity, cookie):
        self.identity = identity
        self.callbacks = {}
        self.stopped = False

    def connect(self, name, callback):
        self.callbacks[name] = callback

    def initiate(self):
        self.callbacks['request'](self, 'Password:', False)

    def response(self, text):
        self.callbacks['completed'](self, text == 'fixture-accepted')

    def cancel(self):
        self.stopped = True
        self.callbacks['completed'](self, False)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.unlocked = True
        self.cancellable = Gio.Cancellable()
        self.outcomes = []
        self.listener = Listener(dialog_factory=FakeDialog, session_factory=FakeSession,
                                 can_prompt=lambda: self.unlocked)

    def begin(self, identities=None, cancellable=None):
        def complete(listener, result, _):
            try:
                self.outcomes.append(listener.initiate_authentication_finish(result))
            except GLib.Error as error:
                self.outcomes.append(error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)
                                     and 'cancelled')
        self.listener.initiate_authentication(
            'test', 'Example dialog', '', Polkit.Details.new(), 'test-token',
            identities or [Polkit.UnixUser.new(1000)], cancellable or self.cancellable, complete, None)

    def flush(self):
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def test_retries_and_clears_field_before_accepting(self):
        self.begin()
        dialog = self.listener.dialog
        self.assertEqual(dialog.prompt, ('Password:', False))
        dialog.secret = 'fixture-invalid'
        self.listener.submit()
        self.assertFalse(dialog.closed)
        self.assertEqual(dialog.secret, '')
        self.assertIn('Try again', dialog.feedback)
        dialog.secret = 'fixture-accepted'
        self.listener.submit()
        self.flush()
        self.assertEqual(self.outcomes, [True])
        self.assertTrue(dialog.closed)
        self.assertEqual(dialog.secret, '')

    def test_cancellation_releases_request_and_dialog(self):
        self.begin()
        dialog, session = self.listener.dialog, self.listener.session
        self.cancellable.cancel()
        self.flush()
        self.assertEqual(self.outcomes, ['cancelled'])
        self.assertTrue(dialog.closed and session.stopped)
        self.assertIsNone(self.listener.current)

    def test_rejects_second_request_and_denies_submission_if_locked(self):
        self.begin()
        first = self.listener.current
        self.begin(cancellable=Gio.Cancellable())
        self.flush()
        self.assertIs(first, self.listener.current)
        self.unlocked = False
        self.listener.dialog.secret = 'fixture-accepted'
        self.listener.submit()
        self.flush()
        self.assertEqual(self.outcomes, [False, False])

    def test_changing_identity_cancels_old_challenge(self):
        self.begin([Polkit.UnixUser.new(1000), Polkit.UnixUser.new(1001)])
        original = self.listener.session
        self.listener.choose(1)
        self.assertTrue(original.stopped)
        self.assertEqual(self.listener.session.identity.get_uid(), 1001)
        self.listener.cancel()
        self.flush()
        self.assertEqual(self.outcomes, [False])

    def test_rejects_spoofed_system_bus_request(self):
        agent = object.__new__(Agent)
        agent.listener = Mock()
        agent.authority = Mock()
        agent.authority.get_name_owner.return_value = ':1.15'
        invocation = Mock()
        agent.dispatch(None, ':1.19', None, None, 'BeginAuthentication', None, invocation)
        invocation.return_dbus_error.assert_called_once()
        agent.listener.begin.assert_not_called()

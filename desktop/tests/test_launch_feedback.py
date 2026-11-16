"""The launch indicator follows outstanding windows, not the gio process."""
import unittest

from launch_feedback import LaunchCue


class LaunchCueTests(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.cue = LaunchCue(lambda: self.now)

    def test_fast_window_does_not_flash(self):
        self.cue.begin('first', 'app', ())
        self.assertFalse(self.cue.visible())
        self.cue.observe([{'id':'app','windows':[{'id':'1'}]}])
        self.now += 1
        self.assertFalse(self.cue.visible())

    def test_same_app_can_open_twice_without_clearing_cue_early(self):
        for name in ('first','second'):
            self.cue.begin(name,'app',('existing',))
        self.now += .25
        self.assertTrue(self.cue.visible())
        self.cue.observe([{'id':'app','windows':[{'id':'existing'},{'id':'2'}]}])
        self.assertTrue(self.cue.visible())
        self.cue.observe([{'id':'app','windows':[{'id':'existing'},{'id':'2'},{'id':'3'}]}])
        self.assertFalse(self.cue.visible())

    def test_app_without_new_window_times_out(self):
        self.cue.begin('one','app',('existing',))
        self.now += 5
        self.assertFalse(self.cue.visible())
        self.assertFalse(self.cue.requests)

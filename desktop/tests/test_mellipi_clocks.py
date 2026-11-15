import unittest

from mellipi_clocks import ClockState, duration


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.boot, self.wall = 100., 1000.
        self.state = ClockState(lambda: self.boot, lambda: self.wall)

    def test_resume_consumes_a_missed_timer_and_alarm_once(self):
        self.state.start_timer(20)
        self.state.alarm_at = 1050
        self.boot, self.wall = 500, 1400
        self.assertEqual(self.state.poll(), ['Timer finished', 'Alarm'])
        self.assertEqual(self.state.poll(), [])

    def test_wall_clock_changes_only_affect_alarm(self):
        self.state.start_timer(60)
        self.state.alarm_at = 1030
        self.boot, self.wall = 105, 1100
        self.assertEqual(self.state.poll(), ['Alarm'])
        self.assertEqual(self.state.timer_remaining(), 55)

    def test_stopwatch_keeps_elapsed_only_while_running(self):
        self.state.toggle_stopwatch()
        self.boot += 12
        self.state.toggle_stopwatch()
        self.boot += 120
        self.state.toggle_stopwatch()
        self.boot += 9
        self.assertEqual(duration(self.state.stopwatch_seconds()), '00:00:21')
        self.state.reset_stopwatch()
        self.assertEqual(self.state.stopwatch_seconds(), 0)

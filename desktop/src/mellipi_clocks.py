"""Calendar's local timer, one-shot alarm, and stopwatch."""
import math
import shutil
import time

from PyQt6.QtCore import QDateTime, QProcess, QTimer, Qt
from PyQt6.QtWidgets import (QApplication, QDateTimeEdit, QHBoxLayout, QLabel, QPushButton,
                              QSpinBox, QTabWidget, QVBoxLayout, QWidget)


def elapsed_clock():
    """Unlike CLOCK_MONOTONIC on Linux, count time spent suspended."""
    clock = getattr(time, 'CLOCK_BOOTTIME', None)
    return time.clock_gettime(clock) if clock is not None else time.monotonic()


class ClockState:
    def __init__(self, elapsed=elapsed_clock, wall=time.time):
        self.elapsed, self.wall = elapsed, wall
        self.timer_end = self.alarm_at = self.stopwatch_start = None
        self.stopwatch_elapsed = 0.

    def start_timer(self, seconds):
        self.timer_end = self.elapsed() + seconds

    def timer_remaining(self):
        return max(0, self.timer_end - self.elapsed()) if self.timer_end is not None else 0

    def stopwatch_seconds(self):
        if self.stopwatch_start is None:
            return self.stopwatch_elapsed
        return self.stopwatch_elapsed + self.elapsed() - self.stopwatch_start

    def toggle_stopwatch(self):
        if self.stopwatch_start is None:
            self.stopwatch_start = self.elapsed()
        else:
            self.stopwatch_elapsed = self.stopwatch_seconds()
            self.stopwatch_start = None

    def reset_stopwatch(self):
        self.stopwatch_start = None
        self.stopwatch_elapsed = 0.

    def poll(self):
        alerts = []
        if self.timer_end is not None and self.timer_remaining() <= 0:
            self.timer_end = None
            alerts.append('Timer finished')
        if self.alarm_at is not None and self.wall() >= self.alarm_at:
            self.alarm_at = None
            alerts.append('Alarm')
        return alerts


def duration(seconds):
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


class ClockPage(QWidget):
    ALERT_HINT = "Keep Calendar open for alerts."

    def __init__(self, calendar):
        super().__init__()
        self.calendar = calendar
        self.state = ClockState()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('Clock tools')
        layout.addWidget(self.tabs, 1)

        timer, self.timer_label = self._tab('Timer', 'Timer remaining')
        row = QHBoxLayout()
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 1440)
        self.minutes.setValue(5)
        self.minutes.setSuffix(' min')
        self.minutes.setAccessibleName('Timer minutes')
        self.seconds = QSpinBox()
        self.seconds.setRange(0, 59)
        self.seconds.setSuffix(' sec')
        self.seconds.setAccessibleName('Timer seconds')
        row.addWidget(self.minutes, 1)
        row.addWidget(self.seconds, 1)
        timer.addLayout(row)
        self.start_timer, self.cancel_timer = self._buttons(
            timer, 'Start timer', self._start_timer, 'Cancel timer', self._cancel_timer)
        self.minutes.valueChanged.connect(self.refresh)
        self.seconds.valueChanged.connect(self.refresh)

        alarm, self.alarm_label = self._tab('Alarm', 'Alarm time')
        self.when = QDateTimeEdit(self._next_minute())
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat('ddd, MMM d yyyy  HH:mm')
        self.when.setAccessibleName('Alarm date and time')
        alarm.addWidget(self.when)
        self.set_alarm, self.cancel_alarm = self._buttons(
            alarm, 'Set alarm', self._set_alarm, 'Cancel alarm', self._cancel_alarm)

        stopwatch, self.stopwatch_label = self._tab('Stopwatch', 'Stopwatch elapsed time')
        self.start_stopwatch, _ = self._buttons(
            stopwatch, 'Start', self._toggle_stopwatch, 'Reset', self._reset_stopwatch)

        self.feedback = QLabel(self.ALERT_HINT)
        self.feedback.setWordWrap(True)
        self.feedback.setObjectName('muted')
        self.feedback.setAccessibleName('Clock status')
        layout.addWidget(self.feedback)
        self.tabs.currentChanged.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _next_minute():
        now = QDateTime.currentDateTime()
        return now.addSecs(60 - now.time().second()).addMSecs(-now.time().msec())

    def _tab(self, title, accessible):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addStretch(1)
        label = QLabel()
        label.setObjectName('clockValue')
        label.setAccessibleName(accessible)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        self.tabs.addTab(widget, title)
        return layout, label

    @staticmethod
    def _buttons(layout, first, first_callback, second, second_callback):
        row = QHBoxLayout()
        buttons = []
        for text, callback in ((first, first_callback), (second, second_callback)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
            buttons.append(button)
        layout.addLayout(row)
        layout.addStretch(1)
        return buttons

    def _start_timer(self):
        seconds = self.minutes.value() * 60 + self.seconds.value()
        if seconds:
            self.state.start_timer(seconds)
            self.feedback.setText(self.ALERT_HINT)
            self.refresh()

    def _cancel_timer(self):
        self.state.timer_end = None
        self.feedback.setText(self.ALERT_HINT)
        self.refresh()

    def _set_alarm(self):
        stamp = self.when.dateTime().toMSecsSinceEpoch() / 1000
        if stamp <= self.state.wall():
            self.feedback.setText('Choose a time in the future.')
            return
        self.state.alarm_at = stamp
        self.feedback.setText(self.ALERT_HINT)
        self.refresh()

    def _cancel_alarm(self):
        self.state.alarm_at = None
        self.feedback.setText(self.ALERT_HINT)
        self.refresh()

    def _toggle_stopwatch(self):
        self.state.toggle_stopwatch()
        self.refresh()

    def _reset_stopwatch(self):
        self.state.reset_stopwatch()
        self.refresh()

    def active_alerts(self):
        return self.state.timer_end is not None or self.state.alarm_at is not None

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.refresh()

    def refresh(self, *_):
        alerts = self.state.poll()
        for alert in alerts:
            self.feedback.setText(alert)
            QApplication.beep()
            QApplication.alert(self.calendar, 4000)
            notify = shutil.which('notify-send')
            if notify:
                QProcess.startDetached(notify, ['-a', 'Mellipi Calendar', alert])
        timing = self.state.timer_end is not None
        alarm = self.state.alarm_at is not None
        running = self.state.stopwatch_start is not None
        self.start_timer.setEnabled(not timing and bool(self.minutes.value() or self.seconds.value()))
        self.cancel_timer.setEnabled(timing)
        self.minutes.setEnabled(not timing)
        self.seconds.setEnabled(not timing)
        self.set_alarm.setEnabled(not alarm)
        self.cancel_alarm.setEnabled(alarm)
        self.when.setEnabled(not alarm)
        self.timer_label.setText(duration(math.ceil(self.state.timer_remaining())) if timing else
                                 duration(self.minutes.value() * 60 + self.seconds.value()))
        self.stopwatch_label.setText(duration(self.state.stopwatch_seconds()))
        self.start_stopwatch.setText('Pause' if running else 'Resume' if self.state.stopwatch_elapsed else 'Start')
        if alarm:
            timestamp = QDateTime.fromMSecsSinceEpoch(round(self.state.alarm_at * 1000))
            self.alarm_label.setText(timestamp.toString('ddd, MMM d · HH:mm'))
        else:
            self.alarm_label.setText('No alarm set')
            if alerts and self.when.dateTime() <= QDateTime.currentDateTime():
                self.when.setDateTime(self._next_minute())
        stopwatch_visible = self.isVisible() and running and self.tabs.currentIndex() == 2
        timer_visible = self.isVisible() and timing and self.tabs.currentIndex() == 0
        interval = 250 if timer_visible or stopwatch_visible else 1000
        if timing or alarm or stopwatch_visible:
            if not self.refresh_timer.isActive() or self.refresh_timer.interval() != interval:
                self.refresh_timer.start(interval)
        else:
            self.refresh_timer.stop()

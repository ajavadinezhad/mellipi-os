"""Calendar's local timer, one-shot alarm, and stopwatch."""
import math
import shutil
import time

from PyQt6.QtCore import QDateTime, QFileSystemWatcher, QProcess, QTimer, Qt
from PyQt6.QtWidgets import (QApplication, QComboBox, QDateTimeEdit, QHBoxLayout, QLabel, QPushButton,
                              QSpinBox, QTabWidget, QVBoxLayout, QWidget)

import mellipi_alarm_queue as alarm_queue


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
        self.alarm_path = alarm_queue.queue_path()
        self.alarm_job = None
        self.alarm_list = {}
        self.saved_timer = None
        self.alarm_watcher = QFileSystemWatcher(self)
        self.alarm_watcher.directoryChanged.connect(self._sync_alarms)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        layout = self.clock_layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('Clock tools')
        layout.addWidget(self.tabs, 1)

        self.tab_layouts = []
        self.tab_controls = []
        self.display_layout = None
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
        presets = QHBoxLayout()
        self.presets = []
        for length in (1, 5, 15, 25):
            button = QPushButton(f'{length} min')
            button.setAccessibleName(f'Start a {length} minute timer')
            button.clicked.connect(lambda _checked=False, minutes=length: self._start_preset(minutes))
            presets.addWidget(button)
            self.presets.append(button)
        timer.addLayout(presets)
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
        self.alarm_choices = QComboBox()
        self.alarm_choices.setAccessibleName('Scheduled alarms')
        alarm.addWidget(self.alarm_choices)
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
        self._sync_alarms()
        self.alarm_choices.currentIndexChanged.connect(
            lambda index: self.cancel_alarm.setEnabled(not self.alarm_job and index >= 0))

    def fit_display(self, font_size, compact):
        if self.display_layout == (font_size, compact):
            return
        self.display_layout = (font_size, compact)
        outer_margin, tab_margin = (2, 4) if compact else (8, 9)
        self.clock_layout.setContentsMargins(outer_margin, outer_margin, outer_margin, outer_margin)
        for tab in self.tab_layouts:
            tab.setContentsMargins(tab_margin, tab_margin, tab_margin, tab_margin)
            tab.setSpacing(3 if compact else 6)
        for controls in self.tab_controls:
            controls.setMaximumWidth(max(300, font_size * 22))
        for label, multiplier in ((self.timer_label, 3), (self.alarm_label, 2), (self.stopwatch_label, 3)):
            size = round(font_size * (multiplier * .60 if compact else multiplier))
            label.setStyleSheet(f'font-size: {size}px;')

    @staticmethod
    def _next_minute():
        now = QDateTime.currentDateTime()
        return now.addSecs(60 - now.time().second()).addMSecs(-now.time().msec())

    def _tab(self, title, accessible):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tab_layouts.append(layout)
        layout.addStretch(1)
        controls = QWidget()
        controls.setMaximumWidth(320)
        self.tab_controls.append(controls)
        group = QVBoxLayout(controls)
        group.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(controls, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        label = QLabel()
        label.setObjectName('clockValue')
        label.setAccessibleName(accessible)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        group.addWidget(label)
        self.tabs.addTab(widget, title)
        return group, label

    @staticmethod
    def _buttons(layout, first, first_callback, second, second_callback):
        row = QHBoxLayout()
        buttons = []
        for text, callback in ((first, first_callback), (second, second_callback)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
            buttons.append(button)
        buttons[0].setProperty('mellipiPrimary', True)
        layout.addLayout(row)
        return buttons

    def _start_timer(self):
        seconds = self.minutes.value() * 60 + self.seconds.value()
        if seconds and not self.saved_timer and not self.alarm_job and self.state.timer_end is None:
            deadline = math.ceil(self.state.wall() + seconds)
            self._alarm_action(['add', str(deadline), '--countdown'],
                               success='Timer running. Calendar can close.',
                               fallback_timer=deadline)

    def _start_preset(self, minutes):
        if self.state.timer_end is None and not self.saved_timer and not self.alarm_job:
            self.minutes.setValue(minutes)
            self.seconds.setValue(0)
            self._start_timer()

    def _cancel_timer(self):
        if self.saved_timer:
            self._alarm_action(['cancel', self.saved_timer[0]], success='Timer canceled.')
            return
        self.state.timer_end = None
        self.feedback.setText(self.ALERT_HINT)
        self.refresh()

    def _set_alarm(self):
        stamp = self.when.dateTime().toMSecsSinceEpoch() / 1000
        if stamp <= self.state.wall():
            self.feedback.setText('Choose a time in the future.')
            return
        self._alarm_action(['add', str(math.ceil(stamp))], success='Alarm saved; Calendar can close.',
                           fallback_stamp=stamp)

    def _cancel_alarm(self):
        key = self.alarm_choices.currentData()
        if key:
            self._alarm_action(['cancel', key], success='Alarm canceled.')
        elif key == '' and self.state.alarm_at is not None:
            self.state.alarm_at = None
            self._remove_local_alarm_choice()
            self.feedback.setText('Alarm canceled.')
            self.refresh()

    def _remove_local_alarm_choice(self):
        index = self.alarm_choices.findData('')
        if index < 0:
            return
        was_selected = self.alarm_choices.currentIndex() == index
        self.alarm_choices.removeItem(index)
        # Do not silently retarget Cancel to a saved alarm.
        if was_selected:
            self.alarm_choices.setCurrentIndex(-1)

    def _sync_alarms(self, *_):
        try:
            path = str(self.alarm_path.parent)
            if path not in self.alarm_watcher.directories() and self.alarm_path.parent.is_dir():
                self.alarm_watcher.addPath(path)
            rows = alarm_queue.read_queue(self.alarm_path)
        except (OSError, ValueError):
            self.feedback.setText('Could not read saved alarms.')
            rows = {}
        current = self.alarm_choices.currentData()
        had_choices = bool(self.alarm_choices.count())
        countdowns = [(key, alarm_queue.alarm_time(row)) for key, row in rows.items() if alarm_queue.is_countdown(row)]
        self.saved_timer = next(iter(countdowns), None)
        rows = {key: row for key, row in rows.items() if not alarm_queue.is_countdown(row)}
        self.alarm_list = rows
        self.alarm_choices.clear()
        for key, entry in sorted(rows.items(), key=lambda item: alarm_queue.alarm_time(item[1])):
            text = QDateTime.fromSecsSinceEpoch(alarm_queue.alarm_time(entry)).toString('ddd, MMM d · HH:mm')
            if label := alarm_queue.alarm_label(entry):
                text = f'{label[:42]} · {text}'
            self.alarm_choices.addItem(text, key)
        if self.state.alarm_at is not None:
            text = QDateTime.fromMSecsSinceEpoch(round(self.state.alarm_at * 1000)).toString('ddd, MMM d · HH:mm')
            self.alarm_choices.addItem(text + ' (local only)', '')
        if had_choices:
            self.alarm_choices.setCurrentIndex(self.alarm_choices.findData(current))
        self.refresh()

    def remind_for_event(self, stamp, title, callback):
        if self.alarm_job:
            callback('Calendar alarms are busy. Try again.')
            return
        self._alarm_action(['add', str(stamp), '--label=' + title],
                           success='Event reminder scheduled.', callback=callback)

    def _alarm_action(self, arguments, *, success, fallback_stamp=None, fallback_timer=None, callback=None):
        if self.alarm_job:
            return
        job = self.alarm_job = QProcess(self)
        job.setProgram('/usr/bin/python3')
        job.setArguments([alarm_queue.__file__, *arguments])

        def finish(ok):
            if self.alarm_job is not job:
                return
            self.alarm_job = None
            if ok:
                self.feedback.setText(success)
            else:
                reason = bytes(job.readAllStandardError()).decode(errors='replace').strip()[:240]
                if fallback_stamp is not None and not reason.startswith(('An alarm', 'Remove an alarm', 'Choose')):
                    self.state.alarm_at = fallback_stamp
                    self.feedback.setText('Background alarms unavailable. Keep Calendar open for this alarm.')
                elif fallback_timer is not None and not reason.startswith(('A countdown', 'Remove an alarm')):
                    self.state.start_timer(max(0, fallback_timer - self.state.wall()))
                    self.feedback.setText('Background timer unavailable. Keep Calendar open.')
                else:
                    self.feedback.setText(reason or 'Could not update the saved alarm.')
            job.deleteLater()
            self._sync_alarms()
            if callback:
                callback(self.feedback.text())

        job.finished.connect(lambda code, status: finish(code == 0 and status == QProcess.ExitStatus.NormalExit))
        job.errorOccurred.connect(lambda error: finish(False) if error == QProcess.ProcessError.FailedToStart else None)
        job.start()
        self.refresh()

    def _toggle_stopwatch(self):
        self.state.toggle_stopwatch()
        self.refresh()

    def _reset_stopwatch(self):
        self.state.reset_stopwatch()
        self.refresh()

    def active_alerts(self):
        return self.alarm_job is not None or self.state.timer_end is not None or self.state.alarm_at is not None

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
        if 'Alarm' in alerts:
            self._remove_local_alarm_choice()
        timing = self.state.timer_end is not None or self.saved_timer is not None
        alarm = self.state.alarm_at is not None
        running = self.state.stopwatch_start is not None
        self.feedback.setVisible(self.tabs.currentIndex() != 2 or self.feedback.text() != self.ALERT_HINT)
        self.start_timer.setEnabled(not self.alarm_job and not timing and bool(self.minutes.value() or self.seconds.value()))
        self.cancel_timer.setEnabled(not self.alarm_job and timing)
        self.minutes.setEnabled(not timing)
        self.seconds.setEnabled(not timing)
        for button in self.presets:
            button.setEnabled(not self.alarm_job and not timing)
        self.set_alarm.setEnabled(not self.alarm_job and not alarm and len(self.alarm_list) < alarm_queue.MAX_ALARMS)
        self.alarm_choices.setVisible(bool(self.alarm_choices.count()))
        self.cancel_alarm.setEnabled(not self.alarm_job and self.alarm_choices.currentIndex() >= 0)
        self.when.setEnabled(not self.alarm_job and not alarm)
        remaining = (max(0, self.saved_timer[1] - self.state.wall()) if self.saved_timer else self.state.timer_remaining())
        self.timer_label.setText(duration(math.ceil(remaining)) if timing else
                                 duration(self.minutes.value() * 60 + self.seconds.value()))
        self.stopwatch_label.setText(duration(self.state.stopwatch_seconds()))
        self.start_stopwatch.setText('Pause' if running else 'Resume' if self.state.stopwatch_elapsed else 'Start')
        if alarm:
            timestamp = QDateTime.fromMSecsSinceEpoch(round(self.state.alarm_at * 1000))
            self.alarm_label.setText(timestamp.toString('ddd, MMM d · HH:mm'))
        elif self.alarm_list:
            self.alarm_label.setText(f'{len(self.alarm_list)} scheduled')
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

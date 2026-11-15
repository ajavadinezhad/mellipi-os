"""Local Mellipi agenda. iCalendar files are read only; events stay on-device."""
from calendar import monthrange
from html import escape
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PyQt6.QtCore import QDate, QSize, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QKeySequence, QShortcut, QTextCharFormat
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QCalendarWidget, QFrame, QHBoxLayout,
                              QLabel, QListWidget, QListWidgetItem, QPushButton, QStackedWidget,
                              QScrollArea, QToolButton, QVBoxLayout, QWidget)

from file_chooser import FileChooser
from installed_launcher import user_environment
from mellipi_clocks import ClockPage
from qt_app import AppWindow, themed_prompt

MAX_SOURCE = 2 * 1024 * 1024
MAX_EVENTS = 2000
MAX_STORE = 4 * 1024 * 1024
MIN_DAY = date(1900, 1, 1)
MAX_DAY = date(2200, 12, 31)
class UnsupportedRecurrence(ValueError):
    pass


_REPEATING = {'RRULE', 'RDATE', 'EXRULE', 'EXDATE', 'RECURRENCE-ID'}
_EVENT_FIELDS = {'UID', 'DTSTART', 'DTEND', 'DURATION', 'SUMMARY', 'LOCATION', 'STATUS', 'SEQUENCE', 'DTSTAMP', *_REPEATING}
_DURATION = re.compile(r'P(?:(?P<weeks>\d{1,4})W|(?:(?P<days>\d{1,4})D)?(?:T(?:(?P<hours>\d{1,5})H)?(?:(?P<minutes>\d{1,5})M)?(?:(?P<seconds>\d{1,5})S)?)?)')


@dataclass(frozen=True)
class Event:
    key: str
    title: str
    location: str
    start: str
    end: str
    all_day: bool
    sequence: int = 0
    stamp: str = ''
    deleted: bool = False
    rule: str = ''

    @property
    def revision(self):
        # A cancellation and a live event at the same revision resolve to
        # the cancellation, so re-importing an old export cannot revive it.
        return self.sequence, self.stamp, self.deleted

    def local(self):
        if self.all_day:
            return date.fromisoformat(self.start), date.fromisoformat(self.end)
        values = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
        # Floating events keep their clock time; zoned events follow the desktop.
        return tuple(value.astimezone().replace(tzinfo=None) if value.tzinfo else value for value in values)

    def span(self):
        start, end = self.local()
        if self.all_day:
            return start, end - timedelta(days=1)
        last = end.date() - timedelta(days=1) if end > start and end.time() == time.min else end.date()
        return start.date(), max(start.date(), last)


def _text(value, limit):
    value = re.sub(r'\\([nN,;\\])', lambda m: ' ' if m[1].lower() == 'n' else m[1], value)
    return ' '.join(''.join(c for c in value if c.isprintable() or c.isspace()).split())[:limit]


def _date_value(params, value):
    if re.fullmatch(r'[0-9]{8}', value):
        result = datetime.strptime(value, '%Y%m%d').date()
    elif re.fullmatch(r'[0-9]{8}T[0-9]{6}Z?', value):
        result = datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S')
        tzid = next((p.split('=',1)[1].strip('"') for p in params if p.upper().startswith('TZID=')), '')
        if value.endswith('Z'):
            result = result.replace(tzinfo=timezone.utc)
        elif tzid:
            if len(tzid) > 128:
                raise ValueError('Invalid time zone')
            result = result.replace(tzinfo=ZoneInfo(tzid))
    else:
        raise ValueError('Invalid calendar date')
    day = result.date() if isinstance(result, datetime) else result
    if not MIN_DAY <= day <= MAX_DAY:
        raise ValueError('Calendar date out of range')
    return result


def _rule(value, start):
    """Parse a deliberately small RFC 5545 subset; keep one record per series."""
    values = {}
    for part in value.split(';'):
        name, separator, argument = part.partition('=')
        name = name.upper()
        if not separator or name in values or name not in ('FREQ', 'INTERVAL', 'COUNT', 'UNTIL'):
            raise UnsupportedRecurrence
        values[name] = argument.upper()
    frequency = values.get('FREQ')
    if frequency not in ('DAILY', 'WEEKLY') or {'COUNT', 'UNTIL'} <= values.keys():
        raise UnsupportedRecurrence
    def positive(name, maximum, default):
        if name not in values:
            return default
        raw = values[name]
        if not re.fullmatch(r'[0-9]{1,6}', raw) or not 1 <= int(raw) <= maximum:
            raise UnsupportedRecurrence
        return int(raw)
    step = timedelta(days=positive('INTERVAL', 366, 1) * (7 if frequency == 'WEEKLY' else 1))
    count = positive('COUNT', 110000, None)
    until = _date_value((), values['UNTIL']) if 'UNTIL' in values else None
    if until is not None and (type(start) is not type(until)
                              or (isinstance(start, datetime) and bool(start.tzinfo) != bool(until.tzinfo))
                              or until < start):
        raise UnsupportedRecurrence
    return step, count, until


def occurrences(event, first, last):
    """Yield instances intersecting the visible range, without walking from DTSTART."""
    first_day, last_day = event.span()
    if not event.rule:
        if first_day <= last and last_day >= first:
            yield event
        return
    parse = date.fromisoformat if event.all_day else datetime.fromisoformat
    start, end = parse(event.start), parse(event.end)
    step, count, until = _rule(event.rule, start)
    # A UTC occurrence's local day can shift by one across DST.
    begin = max(0, ((first - last_day).days - 1) // step.days)
    stop = ((last - first_day).days + 1) // step.days
    if count is not None:
        stop = min(stop, count - 1)
    if until is not None:
        stop = min(stop, (until - start) // step)
    for number in range(begin, stop + 1):
        delta = number * step
        instance = replace(event, start=(start + delta).isoformat(), end=(end + delta).isoformat(), rule='')
        first_day, last_day = instance.span()
        if first_day <= last and last_day >= first:
            yield instance


def _event(fields):
    uid = fields['UID'][1].strip()
    if not uid or len(uid) > 1024:
        raise ValueError('Missing calendar identifier')
    key = hashlib.sha256(uid.encode()).hexdigest()
    sequence = fields.get('SEQUENCE', ((), '0'))[1]
    if not re.fullmatch(r'[0-9]{1,10}', sequence) or int(sequence) > 2147483647:
        raise ValueError('Invalid calendar sequence')
    sequence = int(sequence)
    stamp = fields.get('DTSTAMP', ((), ''))[1]
    if stamp:
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', stamp):
            raise ValueError('Expected a UTC calendar timestamp')
        datetime.strptime(stamp, '%Y%m%dT%H%M%SZ')
    if (_REPEATING - {'RRULE'}).intersection(fields):
        raise UnsupportedRecurrence
    if fields.get('STATUS', ((), ''))[1].upper() == 'CANCELLED':
        return key, Event(key, '', '', '', '', False, sequence, stamp, True)
    start = _date_value(*fields['DTSTART'])
    all_day = not isinstance(start, datetime)
    if 'DTEND' in fields and 'DURATION' in fields:
        raise ValueError('Calendar event has two ends')
    if 'DTEND' in fields:
        end = _date_value(*fields['DTEND'])
    elif 'DURATION' in fields:
        duration = _DURATION.fullmatch(fields['DURATION'][1])
        if not duration or not any(duration.groupdict().values()):
            raise ValueError('Invalid event duration')
        parts = {name: int(value or 0) for name, value in duration.groupdict().items()}
        if all_day and any(parts[key] for key in ('hours', 'minutes', 'seconds')):
            raise ValueError('Invalid all-day duration')
        delta = timedelta(**parts)
        if delta <= timedelta(0) or delta > timedelta(days=3660):
            raise ValueError('Event duration out of range')
        if all_day or not start.tzinfo:
            end = start + delta
        else:
            # Calendar days are wall-clock days; time units are elapsed time.
            days = timedelta(weeks=parts['weeks'], days=parts['days'])
            clock = timedelta(hours=parts['hours'], minutes=parts['minutes'], seconds=parts['seconds'])
            end = ((start + days).astimezone(timezone.utc) + clock).astimezone(start.tzinfo)
    else:
        end = start + timedelta(days=1) if all_day else start
    if type(start) is not type(end):
        raise ValueError('Calendar start and end use different date types')
    if not all_day and (bool(start.tzinfo) != bool(end.tzinfo)):
        raise ValueError('Calendar start and end use incompatible time zones')
    if not all_day and start.tzinfo:
        chronological_start = start.astimezone(timezone.utc)
        chronological_end = end.astimezone(timezone.utc)
    else:
        chronological_start, chronological_end = start, end
    if chronological_end < chronological_start or (all_day and end == start):
        raise ValueError('Calendar event ends before it starts')
    rule = fields.get('RRULE', ((), ''))[1]
    if 'RRULE' in fields:
        if any(p.upper().startswith('TZID=') for name in ('DTSTART', 'DTEND')
               for p in fields.get(name, ((), ''))[0]):
            raise UnsupportedRecurrence
        step, _, _ = _rule(rule, start)
        if chronological_end - chronological_start > min(step, timedelta(days=31)):
            raise UnsupportedRecurrence
    title = _text(fields.get('SUMMARY', ((), ''))[1], 240) or 'Untitled event'
    location = _text(fields.get('LOCATION', ((), ''))[1], 220)
    return key, Event(key, title, location, start.isoformat(), end.isoformat(), all_day, sequence, stamp, rule=rule)


def parse_ics(raw):
    """Return changes keyed by UID and counts for unsupported or invalid events."""
    if len(raw) > MAX_SOURCE:
        raise ValueError('Choose an iCalendar file smaller than 2 MiB')
    try:
        unfolded = re.sub(rb'(?:\r\n|\n)[ \t]', b'', raw).decode('utf-8-sig')
    except UnicodeError as error:
        raise ValueError('The calendar is not UTF-8') from error
    lines = [line.removesuffix('\r') for line in unfolded.split('\n') if line.strip()]
    if not lines or lines[0].upper() != 'BEGIN:VCALENDAR' or lines[-1].upper() != 'END:VCALENDAR':
        raise ValueError('This is not an iCalendar file')
    changes, stack, fields = {}, [], {}
    blocked_series = set()
    skipped, recurring, count = 0, 0, 0
    for line in lines:
        if len(line)>65536:
            continue
        # An unquoted colon ends the parameter list.
        match = re.fullmatch(r'((?:[^":]|"[^"]*")*):(.*)', line)
        if not match:
            continue
        head, value = match.groups()
        name, *params = head.split(';')
        name = name.upper()
        if name == 'BEGIN':
            stack.append(value.upper())
            if len(stack) > 16:
                raise ValueError('Calendar nesting is too deep')
            if stack == ['VCALENDAR', 'VEVENT']:
                fields = {}
                count += 1
                if count > MAX_EVENTS:
                    raise ValueError('Choose a calendar with at most 2,000 events')
        elif name == 'END':
            if not stack or stack[-1] != value.upper():
                raise ValueError('Calendar components do not match')
            if stack == ['VCALENDAR', 'VEVENT']:
                try:
                    key, event = _event(fields)
                    if key not in changes or event.revision >= changes[key].revision:
                        changes[key] = event
                except UnsupportedRecurrence:
                    recurring += 1
                    uid = fields.get('UID', ((), ''))[1].strip()
                    if uid and len(uid) <= 1024:
                        blocked_series.add(hashlib.sha256(uid.encode()).hexdigest())
                except (KeyError, TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
                    skipped += 1
            stack.pop()
        elif stack == ['VCALENDAR', 'VEVENT'] and name in _EVENT_FIELDS:
            if name == 'RRULE' and name in fields:
                fields['EXRULE'] = ((), '')
            fields[name] = (params, value)
    if stack:
        raise ValueError('The calendar is incomplete')
    for key in blocked_series:
        # Do not present a partial series when its included overrides cannot
        # be applied; retain any previously imported revision.
        event = changes.get(key)
        if event and not event.deleted:
            del changes[key]
    return changes, recurring, skipped


def read_local(path, maximum):
    # Reject devices/FIFOs without blocking and do not fetch external resources.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Choose a regular local file')
        if info.st_size > maximum:
            raise ValueError('File exceeds the supported size')
        data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError('File exceeds the supported size')
        return data


class EventStore:
    def __init__(self, path):
        self.path = path
        self.records = {}
        self.error = ''
        try:
            rows = json.loads(read_local(path, MAX_STORE))
            if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
                raise ValueError('Invalid calendar store')
            for row in rows:
                event = Event(**row)
                if (not re.fullmatch(r'[a-f0-9]{64}', event.key) or type(event.all_day) is not bool
                        or not isinstance(event.title, str) or len(event.title)>240
                        or not isinstance(event.location, str) or len(event.location)>220):
                    raise ValueError('Invalid saved event')
                if (type(event.sequence) is not int or not 0 <= event.sequence <= 2147483647
                        or type(event.deleted) is not bool or not isinstance(event.stamp, str)
                        or (event.stamp and not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', event.stamp))):
                    raise ValueError('Invalid calendar revision')
                if not isinstance(event.rule, str) or len(event.rule) > 128:
                    raise ValueError('Invalid saved repeat rule')
                if not event.deleted:
                    event.span()
                    if event.rule:
                        parse = date.fromisoformat if event.all_day else datetime.fromisoformat
                        start, end = parse(event.start), parse(event.end)
                        step, _, _ = _rule(event.rule, start)
                        if end - start > min(step, timedelta(days=31)):
                            raise ValueError('Invalid recurring event duration')
                self.records[event.key] = event
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError, OverflowError):
            self.records.clear()
            self.error = 'Saved events could not be read. Move the calendar data file aside before importing.'

    @property
    def events(self):
        return {key: event for key, event in self.records.items() if not event.deleted}

    def import_path(self, source):
        changes, recurring, skipped = parse_ics(read_local(source, MAX_SOURCE))
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name+'.lock')
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError('The calendar lock is not a regular file')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('Another Calendar window is importing events. Try again shortly.') from error
            # Another Calendar instance may have saved changes since this one opened.
            current = EventStore(self.path)
            if current.error:
                raise ValueError(current.error)
            self.records = current.records
            self.error = ''
            imported = self._merge(changes)
        finally:
            os.close(descriptor)
        return imported, recurring, skipped

    def _merge(self, changes):
        updated = dict(self.records)
        imported = []
        for key, event in changes.items():
            previous = updated.get(key)
            if previous is not None and event.revision < previous.revision:
                continue
            # Legacy exports may have neither field, so allow updates between
            # two unversioned live events. With an explicit revision, ties
            # cannot establish which live version is newer.
            if previous and not event.deleted and event.revision == previous.revision and (event.sequence or event.stamp):
                continue
            updated[key] = event
            if not event.deleted:
                imported.append(event)
        if len(updated) > MAX_EVENTS:
            raise ValueError('The local calendar limit is 2,000 events')
        if updated != self.records:
            payload = json.dumps([asdict(event) for event in updated.values()], ensure_ascii=False)
            if len(payload.encode('utf-8')) > MAX_STORE:
                raise ValueError('The local calendar data is too large')
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.calendar-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            self.records = updated
        return imported


def _qdate(day):
    return QDate(day.year, day.month, day.day)


class Calendar(AppWindow):
    extra_style = """
        QListWidget#dayEvents { padding: 4px; background: %(surface)s; }
        QListWidget#dayEvents::item { padding: 6px 8px; }
        QLabel#agendaDate {
            color: %(accent_ink)s; background: %(selected_surface)s; font-weight: 600;
            border-radius: %(radius)dpx; padding: %(padding)dpx 8px;
        }
        QListWidget#dayEvents::item { padding: 4px 8px; }
        QListWidget#dayEvents::item:hover { background: %(selected_surface)s; }
        QLabel#clockValue { color: %(accent_ink)s; font-weight: 600; }
        QCalendarWidget QToolButton { color: %(text)s; }
        QCalendarWidget QWidget#qt_calendar_navigationbar { background: %(surface)s; }
        QCalendarWidget QToolButton:focus { border: 1px solid %(focus)s; }
        QCalendarWidget QAbstractItemView::item:selected {
            background: %(accent)s;
            color: %(accent_text)s;
        }
    """

    def __init__(self):
        super().__init__('Calendar')
        self.resize(760, 485)
        self.setMinimumSize(450, 300)
        self.store = EventStore(Path(user_environment()['ORBIT_DATA'])/'calendar-events.json')
        self.marked = []
        self.month = QCalendarWidget()
        self.month.setAccessibleName('Choose a day')
        for control_name, icon, description in (
            ('qt_calendar_prevmonth', 'go-previous', 'Previous month'),
            ('qt_calendar_nextmonth', 'go-next', 'Next month'),
        ):
            control = self.month.findChild(QToolButton, control_name)
            if control is not None:
                control.setAccessibleName(description)
                control.setToolTip(description)
                control.setProperty('mellipiSymbolicIcon', icon)
        self.month.setMinimumDate(_qdate(MIN_DAY))
        self.month.setMaximumDate(_qdate(MAX_DAY))
        self.month.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.month.selectionChanged.connect(self.refresh_day)
        self.month.currentPageChanged.connect(self.refresh_month)
        self.event_list = QListWidget()
        self.event_list.setObjectName('dayEvents')
        self.event_list.setAccessibleName('Events on the selected day')
        self.agenda_date = QLabel()
        self.agenda_date.setObjectName('agendaDate')
        self.empty = QLabel('No events')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName('muted')
        self.status = QLabel(self.store.error or '')
        self.status.setAccessibleName('Calendar import status')
        self.status.setObjectName('muted')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setVisible(bool(self.status.text()))

        today = QPushButton()
        today.setAccessibleName('Go to today')
        today.setToolTip('Go to today')
        today.setProperty('mellipiSymbolicIcon', 'calendar-today')
        today.setMinimumSize(32, 32)
        today.clicked.connect(lambda: self.month.setSelectedDate(QDate.currentDate()))
        import_button = QPushButton()
        import_button.setAccessibleName('Import a local iCalendar file')
        import_button.setMinimumSize(32, 32)
        import_button.setProperty('mellipiSymbolicIcon','document-open')
        import_button.setToolTip('Import a local iCalendar file')
        import_button.clicked.connect(self.choose_import)
        self.clock_button = QPushButton('Clocks')
        self.clock_button.setToolTip('Timer, alarm and stopwatch')
        self.clock_button.setProperty('mellipiSymbolicIcon', 'preferences-system-time')
        self.clock_button.clicked.connect(lambda: self.show_clocks(self.pages.currentIndex() == 0))
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.action_buttons = (today, import_button, self.clock_button)
        actions.addWidget(self.clock_button)
        actions.addStretch(1)
        actions.addWidget(today)
        actions.addWidget(import_button)
        self.content.addLayout(actions)

        agenda = QVBoxLayout()
        agenda.setSpacing(8)
        agenda.addWidget(self.agenda_date)
        agenda.addWidget(self.event_list, 1)
        agenda.addWidget(self.empty, 1)
        self.day_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.day_layout.setSpacing(12)
        self.day_layout.addWidget(self.month, 3)
        self.day_layout.addLayout(agenda, 2)
        calendar_page = QWidget()
        calendar_layout = QVBoxLayout(calendar_page)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        calendar_layout.addLayout(self.day_layout, 1)
        calendar_layout.addWidget(self.status)
        self.clock_page = ClockPage(self)
        self.pages = QStackedWidget()
        self.month_scroll = self.scroll_page(calendar_page)
        self.pages.addWidget(self.month_scroll)
        self.pages.addWidget(self.scroll_page(self.clock_page))
        self.content.addWidget(self.pages, 1)
        self.calendar_buttons = (today, import_button)
        QShortcut(QKeySequence.StandardKey.Open, self).activated.connect(self.choose_import)
        QShortcut(QKeySequence('Ctrl+Shift+T'), self).activated.connect(
            lambda: self.show_clocks(self.pages.currentIndex() == 0))
        self.themeChanged.connect(self.refresh_all)
        self.refresh_icons()
        self.refresh_all()
        self.month.setFocus()

    @staticmethod
    def scroll_page(page):
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def show_clocks(self, enabled=True):
        self.pages.setCurrentIndex(int(enabled))
        self.clock_button.setText('Calendar' if enabled else 'Clocks')
        self.clock_button.setToolTip('Return to calendar' if enabled else 'Timer, alarm and stopwatch')
        self.clock_button.setProperty('mellipiSymbolicIcon', 'calendar' if enabled else 'preferences-system-time')
        for button in self.calendar_buttons:
            button.setVisible(not enabled)
        self.refresh_icons()

    def closeEvent(self, event):
        if self.clock_page.active_alerts() and not themed_prompt(
            self, 'Close Calendar?', 'Closing Calendar cancels your timer and alarm.', 'Close Calendar', 'Keep open'
        ):
            event.ignore()
            return
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'day_layout'):
            self.update_layout()

    def update_layout(self):
        # Reserve a readable agenda column before choosing the side-by-side layout.
        narrow = self.width() < 640 + max(0, self.theme['font_size']-14) * 15
        direction = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if self.day_layout.direction() != direction:
            self.day_layout.setDirection(direction)
        font_size = self.theme['font_size']
        glyph = max(16, min(24, font_size + 2))
        for label, scale in ((self.clock_page.timer_label, 3), (self.clock_page.alarm_label, 2),
                             (self.clock_page.stopwatch_label, 3)):
            label.setStyleSheet(f'font-size: {font_size * scale}px;')
        for button in self.action_buttons:
            button.setIconSize(QSize(glyph, glyph))
            button.setMinimumSize(glyph + 18, glyph + 14)
        self.month.setMinimumHeight(7 * (font_size + 4) + font_size + 18)
        # Give the agenda usable space inside the scrollable page, rather than
        # forcing a window taller than small or scaled displays.
        self.event_list.setMinimumHeight(font_size * 3 + 18)
        self.empty.setMinimumHeight(font_size * 2 + 10)

    def refresh_all(self):
        weekend = QTextCharFormat()
        weekend.setForeground(QBrush(QColor(self.theme['muted'])))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.month.setWeekdayTextFormat(day, weekend)
        self.update_layout()
        self.refresh_month(self.month.yearShown(), self.month.monthShown())
        self.refresh_day()

    def refresh_month(self, year, month):
        for day in self.marked:
            self.month.setDateTextFormat(day, QTextCharFormat())
        self.marked = []
        ink = QTextCharFormat()
        ink.setForeground(QBrush(QColor(self.theme['accent_ink'])))
        ink.setFontWeight(QFont.Weight.Bold)
        first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
        days = set()
        for event in self.store.events.values():
            if len(days) == last.day:
                break
            for instance in occurrences(event, first, last):
                start, end = instance.span()
                current, stop = max(start, first), min(end, last)
                while current <= stop:
                    days.add(current)
                    current += timedelta(days=1)
        now = QDate.currentDate()
        if now.year() == year and now.month() == month:
            days.add(date(year, month, now.day()))
        for day in days:
            qt_day = _qdate(day)
            style = QTextCharFormat(ink)
            if qt_day == now:
                # The underline distinguishes Today from imported event days.
                style.setFontUnderline(True)
            self.month.setDateTextFormat(qt_day, style)
            self.marked.append(qt_day)

    def refresh_day(self):
        selected = self.month.selectedDate()
        if not hasattr(self, 'agenda_date'):
            return
        self.agenda_date.setText(selected.toString('ddd, MMM d'))
        day = date(selected.year(), selected.month(), selected.day())
        rows = [instance for event in self.store.events.values() for instance in occurrences(event, day, day)]
        rows.sort(key=lambda event: (not event.all_day, event.local()[0], event.title.casefold()))
        self.event_list.clear()
        def clock(value):
            if self.theme_watch.preferences.values['clock24']:
                return value.strftime('%H:%M')
            return value.strftime('%I:%M %p').lstrip('0')
        for event in rows:
            start, end = event.local()
            if event.all_day:
                when = 'All day'
            elif start.date() < day:
                when = f'Until {clock(end)}' if end.date() == day else 'Continues today'
            elif end.date() == day and end > start:
                when = f'{clock(start)}–{clock(end)}'
            else:
                when = clock(start)
            detail = when + (' · ' + event.location if event.location else '')
            item = QListWidgetItem(f'{event.title}\n{detail}')
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f'{event.title}, {detail}')
            item.setToolTip(f'<b>{escape(event.title)}</b><br>{escape(detail)}')
            self.event_list.addItem(item)
        self.empty.setVisible(not rows)
        self.event_list.setVisible(bool(rows))

    def choose_import(self):
        path, _ = FileChooser.getOpenFileName(self, 'Import calendar events', str(Path.home()),
                                             'iCalendar (*.ics);;All files (*)')
        if path:
            self.import_file(path)

    def import_file(self, value):
        try:
            if '://' in value or value.startswith('file:'):
                url = QUrl(value)
                if not url.isLocalFile() or url.host() not in ('', 'localhost'):
                    raise ValueError('Only local calendar files can be imported')
                value = url.toLocalFile()
            imported, recurrence, skipped = self.store.import_path(Path(value))
        except (OSError, ValueError) as error:
            self.status.setText(f'Import failed: {error}')
            self.status.show()
            return
        count = len(imported)
        if imported:
            today = date.today()
            days = [event.span() for event in imported]
            selected = self.month.selectedDate()
            selected_day = date(selected.year(), selected.month(), selected.day())
            if not any(next(occurrences(event, selected_day, selected_day), None) for event in imported):
                upcoming = []
                for event in imported:
                    limit = min(MAX_DAY, today + timedelta(weeks=366))
                    instance = next(occurrences(event, today, limit), None)
                    if instance:
                        upcoming.append(max(today, instance.span()[0]))
                target = min(upcoming, default=min(
                    (start for start, _ in days), key=lambda start: abs((start-today).days)))
                self.month.setSelectedDate(_qdate(target))
        summary = [f'Imported or updated {count} event' + ('' if count == 1 else 's')]
        if recurrence:
            summary.append(f'{recurrence} unsupported repeating event entries skipped')
        if skipped:
            summary.append(f'{skipped} invalid event entries or unknown time zones skipped')
        self.status.setText(' · '.join(summary))
        self.status.show()
        self.refresh_all()


def main():
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Calendar')
    app.setOrganizationName('Mellipi')
    app.setDesktopFileName('mellipi-calendar')
    app.setWindowIcon(QIcon.fromTheme('mellipi-calendar', QIcon.fromTheme('x-office-calendar')))
    window = Calendar()
    window.show()
    if len(sys.argv) > 1:
        if sys.argv[1] == '--clocks':
            window.show_clocks()
        else:
            window.import_file(sys.argv[1])
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

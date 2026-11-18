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
import time as wall_clock
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PyQt6.QtCore import QDate, QDateTime, QLocale, QRectF, QSize, QTime, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QIcon, QKeySequence, QPainter, QShortcut, QTextCharFormat
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDateEdit,
                              QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
                              QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                              QStackedWidget, QSizePolicy, QScrollArea, QTableView, QTimeEdit, QVBoxLayout, QWidget)

from file_chooser import FileChooser
from installed_launcher import user_environment
from mellipi_clocks import ClockPage
from qt_app import AppWindow, exec_owned_dialog, style_dialog, themed_prompt

MAX_SOURCE = 2 * 1024 * 1024
MAX_EVENTS = 2000
MAX_STORE = 4 * 1024 * 1024
MIN_DAY = date(1900, 1, 1)
MAX_DAY = date(2200, 12, 31)
class UnsupportedRecurrence(ValueError):
    pass


_REPEATING = {'RRULE', 'RDATE', 'EXRULE', 'EXDATE', 'RECURRENCE-ID'}
PERSONAL_CALENDAR_STEPS = {'FREQ=MONTHLY': 1, 'FREQ=YEARLY': 12}
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
    personal: bool = False

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

    def reminder_stamp(self):
        if self.all_day:
            return int(datetime.combine(date.fromisoformat(self.start), time(9)).timestamp())
        return int(datetime.fromisoformat(self.start).timestamp()) - 300


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
    if event.personal and event.rule in PERSONAL_CALENDAR_STEPS:
        step = PERSONAL_CALENDAR_STEPS[event.rule]
        anchor = start.year * 12 + start.month - 1
        first_month = first.year * 12 + first.month - 1
        last_month = last.year * 12 + last.month - 1
        for index in range(max(0, (first_month - anchor - 1) // step),
                           (last_month - anchor + 1) // step + 1):
            year, month = divmod(anchor + index * step, 12)
            try:
                when = start.replace(year=year, month=month + 1)
            except ValueError:
                continue  # Skip months without the anchor day, including non-leap years.
            instance = replace(event, start=when.isoformat(),
                               end=(when + (end - start)).isoformat(), rule='')
            a, b = instance.span()
            if MIN_DAY <= a <= last and b >= first and a <= MAX_DAY:
                yield instance
        return
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


class EventConflict(ValueError):
    """A local event was replaced or removed since the user opened it."""


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
                        or not isinstance(event.location, str) or len(event.location)>220
                        or type(event.personal) is not bool):
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
                        step = (timedelta(days=31) if event.personal and event.rule in PERSONAL_CALENDAR_STEPS
                                else _rule(event.rule, start)[0])
                        if end - start > min(step, timedelta(days=31)):
                            raise ValueError('Invalid recurring event duration')
                self.records[event.key] = event
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError, OverflowError):
            self.records.clear()
            self.error = 'Saved events could not be read. Move the calendar data file aside before saving changes.'

    @property
    def events(self):
        return {key: event for key, event in self.records.items() if not event.deleted}

    def import_path(self, source):
        changes, recurring, skipped = parse_ics(read_local(source, MAX_SOURCE))
        imported = self._locked_update(lambda: self._merge(
            {key: event for key, event in changes.items() if not (key in self.records and self.records[key].personal)}))
        return imported, recurring, skipped

    def save_personal(self, title, location, day, start=None, end=None, *, key=None, repeat='', expected=None):
        def clean(value, size):
            return ' '.join(''.join(char for char in value if char.isprintable() or char.isspace()).split())[:size]
        title, location = clean(title, 240), clean(location, 220)
        if not title or not MIN_DAY <= day <= MAX_DAY:
            raise ValueError('Enter an event title and a valid date')
        if repeat not in ('', 'FREQ=DAILY', 'FREQ=WEEKLY', *PERSONAL_CALENDAR_STEPS):
            raise ValueError('Choose a supported repeat interval')
        all_day = start is None and end is None
        if all_day:
            start, end = day, day + timedelta(days=1)
        elif start is None or end is None or start >= end:
            raise ValueError('The end time must be after the start time')
        else:
            start, end = datetime.combine(day, start), datetime.combine(day, end)
        expected = self.records.get(key) if expected is None and key is not None else expected
        def save():
            if key is not None:
                self.check_personal_revision(key, expected)
            event = Event(key or hashlib.sha256(uuid.uuid4().bytes).hexdigest(), title, location,
                          start.isoformat(), end.isoformat(), all_day, personal=True, rule=repeat)
            self._write({**self.records, event.key: event})
            return event
        return self._locked_update(save)

    def check_personal_revision(self, key, expected):
        current = self.records.get(key)
        if current is None or not current.personal:
            raise EventConflict('This local event no longer exists.')
        if current != expected:
            raise EventConflict('This event changed in another Calendar window. Your changes were not saved.')

    def remove_personal(self, key, *, expected=None):
        expected = self.records.get(key) if expected is None else expected
        def remove():
            self.check_personal_revision(key, expected)
            self._write({ident: event for ident, event in self.records.items() if ident != key})
        self._locked_update(remove)

    def _locked_update(self, operation):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name+'.lock')
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError('The calendar lock is not a regular file')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('Another Calendar window is saving events. Try again shortly.') from error
            # Another Calendar instance may have saved changes since this one opened.
            current = EventStore(self.path)
            if current.error:
                raise ValueError(current.error)
            self.records = current.records
            self.error = ''
            return operation()
        finally:
            os.close(descriptor)

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
        self._write(updated)
        return imported

    def _write(self, updated):
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


def _qdate(day):
    return QDate(day.year, day.month, day.day)


class MonthGrid(QCalendarWidget):
    """Keep Qt's keyboard and accessible calendar model with Mellipi day markers."""
    ink = None

    def paintCell(self, painter, rect, day):
        if self.ink is None:
            super().paintCell(painter, rect, day)
            return
        ink = self.ink
        selected = day == self.selectedDate()
        today = day == QDate.currentDate()
        marked = day.toJulianDay() in self.event_days
        in_month = day.month() == self.monthShown()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(rect, QColor(ink['surface']))
        diameter = max(16, min(rect.width() - 3, rect.height() - 3, ink['font_size'] + 16))
        badge = QRectF(rect.center().x() - diameter / 2, rect.center().y() - diameter / 2, diameter, diameter)
        if selected or today:
            painter.setPen(Qt.PenStyle.NoPen if selected else QColor(ink['focus']))
            painter.setBrush(QColor(ink['accent']) if selected else Qt.BrushStyle.NoBrush)
            painter.drawEllipse(badge)
        color = ink['accent_text'] if selected else ink['accent_ink'] if today else ink['text'] if in_month else ink['muted']
        painter.setPen(QColor(color))
        font = painter.font()
        font.setBold(selected or today)
        painter.setFont(font)
        day_rect = rect.adjusted(0, -2 if marked and rect.height() >= 24 else 0, 0, -2 if marked and rect.height() >= 24 else 0)
        painter.drawText(day_rect, Qt.AlignmentFlag.AlignCenter, str(day.day()))
        if marked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ink['accent_text'] if selected else ink['accent_ink']))
            painter.drawEllipse(QRectF(rect.center().x() - 2, min(rect.bottom() - 4, badge.bottom() - 4), 4, 4))
        painter.restore()


class Calendar(AppWindow):
    extra_style = """
        QFrame#agendaPanel { background: %(raised)s; border-radius: %(radius)dpx; }
        QListWidget#dayEvents { padding: 4px; background: %(raised)s; }
        QLabel#agendaDate { color: %(accent_ink)s; font-weight: 700; }
        QPushButton#calendarMonth {
            font-weight: 700; text-align: left; background: transparent;
        }
        QPushButton#calendarMonth:hover { background: %(hover)s; }
        QLabel#calendarSection { color: %(text)s; font-weight: 700; }
        QPushButton#newEvent { background: %(selected_surface)s; color: %(accent_ink)s; font-weight: 600; }
        QPushButton#newEvent:hover { border-color: %(focus)s; }
        QListWidget#dayEvents::item { padding: 4px 8px; }
        QListWidget#dayEvents::item:hover { background: %(selected_surface)s; }
        QLabel#clockValue { color: %(accent_ink)s; font-weight: 600; }
        QCalendarWidget QTableView:focus { border-color: %(focus)s; }
    """

    def __init__(self):
        super().__init__('Calendar')
        self.resize(760, 485)
        self.setMinimumSize(450, 300)
        self.store = EventStore(Path(user_environment()['ORBIT_DATA'])/'calendar-events.json')
        self.month_cache = None
        self.month = MonthGrid()
        self.month.event_days = set()
        self.month.setNavigationBarVisible(False)
        self.month.setGridVisible(False)
        self.month.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.month.setAccessibleName('Choose a day')
        # Qt's hidden header otherwise imposes a 64px minimum per day in
        # comfortable 150% layouts, clipping Sunday despite a stretchy grid.
        month_view = self.month_table = self.month.findChild(QTableView, 'qt_calendar_calendarview')
        if month_view is not None:
            month_view.horizontalHeader().setMinimumSectionSize(28)
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
        self.agenda_day = QLabel(objectName='calendarSection')
        self.agenda_day.setWordWrap(True)
        self.agenda_caption = QLabel(objectName='muted')
        self.agenda_caption.setWordWrap(True)
        self.status = QLabel(self.store.error or '')
        self.status.setAccessibleName('Calendar status')
        self.status.setObjectName('muted')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setVisible(bool(self.status.text()))

        today = QPushButton('Today')
        today.setAccessibleName('Go to today')
        today.setToolTip('Go to today')
        today.setProperty('mellipiSymbolicIcon', 'calendar-today')
        today.setMinimumSize(32, 32)
        today.clicked.connect(lambda: self.month.setSelectedDate(QDate.currentDate()))
        import_button = QPushButton('Import…')
        import_button.setAccessibleName('Import a local iCalendar file')
        import_button.setMinimumSize(32, 32)
        import_button.setProperty('mellipiSymbolicIcon','document-open')
        import_button.setToolTip('Import a local iCalendar file')
        import_button.clicked.connect(self.choose_import)
        add_button = self.event_button('New event', 'plus', self.edit_event)
        add_button.setText('New event')
        add_button.setObjectName('newEvent')
        self.edit_button = self.event_button('Open selected event', 'document-open', self.open_selected)
        self.delete_button = self.event_button('Delete selected event', 'trash', self.delete_event)
        self.remind_button = self.event_button('Remind me about this occurrence', 'notifications', self.remind_selected)
        self.event_list.itemSelectionChanged.connect(self.event_actions)
        self.event_list.itemActivated.connect(lambda _item: self.open_selected())
        self.clock_button = QPushButton('Clocks')
        self.clock_button.setToolTip('Timer, alarm and stopwatch')
        self.clock_button.setProperty('mellipiSymbolicIcon', 'preferences-system-time')
        self.clock_button.clicked.connect(lambda: self.show_clocks(True))
        self.calendar_button = QPushButton('Calendar')
        self.calendar_button.setProperty('mellipiSymbolicIcon', 'calendar')
        self.calendar_button.clicked.connect(lambda: self.show_clocks(False))
        modes = QButtonGroup(self)
        for button in (self.calendar_button, self.clock_button):
            button.setCheckable(True)
            modes.addButton(button)
        self.calendar_button.setChecked(True)
        actions = QHBoxLayout()
        previous = self.event_button('Previous month', 'go-previous', self.month.showPreviousMonth)
        following = self.event_button('Next month', 'go-next', self.month.showNextMonth)
        self.month_label = QPushButton(objectName='calendarMonth')
        self.month_label.setToolTip('Jump to a date')
        self.month_label.clicked.connect(self.jump_to_date)
        self.action_buttons = (today, previous, following, import_button, add_button, self.edit_button,
                               self.delete_button, self.remind_button, self.calendar_button, self.clock_button)
        actions.addWidget(self.calendar_button)
        actions.addWidget(self.clock_button)
        actions.addStretch(1)
        self.search_button = self.event_button('Find an event', 'edit-find', self.find_events)
        actions.addWidget(import_button)
        self.mode_row = actions
        self.content.addLayout(actions)

        month_panel = QVBoxLayout()
        month_row = QHBoxLayout()
        month_row.addWidget(self.month_label, 1)
        month_row.addWidget(previous)
        month_row.addWidget(following)
        month_row.addWidget(today)
        month_panel.addLayout(month_row)
        month_panel.addWidget(self.month, 1)
        self.agenda_panel = QFrame(objectName='agendaPanel')
        agenda = QVBoxLayout(self.agenda_panel)
        self.agenda_layout = agenda
        self.space_controls(actions, month_row, agenda)
        date_heading = QHBoxLayout()
        date_heading.addWidget(self.agenda_date)
        date_heading.addWidget(self.agenda_day, 1)
        agenda.addLayout(date_heading)
        agenda.addWidget(self.agenda_caption)
        date_row = QHBoxLayout()
        date_row.addWidget(add_button)
        date_row.addWidget(self.search_button)
        date_row.addStretch(1)
        self.agenda_row = date_row
        self.add_button = add_button
        agenda.addLayout(date_row)
        agenda.addWidget(self.event_list, 1)
        self.empty_space = QWidget()
        agenda.addWidget(self.empty_space, 1)
        self.event_toolbar = QWidget()
        event_row = QHBoxLayout(self.event_toolbar)
        event_row.setContentsMargins(0, 0, 0, 0)
        event_row.addStretch(1)
        event_row.addWidget(self.remind_button)
        event_row.addWidget(self.edit_button)
        event_row.addWidget(self.delete_button)
        agenda.addWidget(self.event_toolbar)
        self.space_controls(date_row, event_row)
        self.day_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.day_layout.setSpacing(12)
        self.day_layout.addLayout(month_panel, 3)
        self.day_layout.addWidget(self.agenda_panel, 2)
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
        self.import_button = import_button
        self.compact_actions = False
        QShortcut(QKeySequence.StandardKey.Open, self).activated.connect(self.choose_import)
        QShortcut(QKeySequence.StandardKey.Find, self).activated.connect(
            lambda: self.find_events() if self.pages.currentIndex() == 0 else None)
        QShortcut(QKeySequence.StandardKey.New, self).activated.connect(
            lambda: self.edit_event() if self.pages.currentIndex() == 0 else None)
        QShortcut(QKeySequence('Ctrl+Shift+T'), self).activated.connect(
            lambda: self.show_clocks(self.pages.currentIndex() == 0))
        self.themeChanged.connect(self.refresh_all)
        self.refresh_icons()
        self.refresh_all()
        self.month.setFocus()

    @staticmethod
    def event_button(label, icon, callback):
        button = QPushButton()
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setProperty('mellipiSymbolicIcon', icon)
        button.clicked.connect(lambda _checked: callback())
        return button

    @staticmethod
    def scroll_page(page):
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def jump_to_date(self):
        dialog = style_dialog(QDialog(self), self)
        dialog.setWindowTitle('Jump to date')
        layout = QFormLayout(dialog)
        date_input = QDateEdit(self.month.selectedDate(), calendarPopup=True)
        date_input.setDateRange(self.month.minimumDate(), self.month.maximumDate())
        date_input.setAccessibleName('Date to jump to')
        layout.addRow('Date', date_input)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addRow(controls)
        if exec_owned_dialog(dialog) == QDialog.DialogCode.Accepted:
            self.month.setSelectedDate(date_input.date())

    def find_events(self):
        dialog = style_dialog(QDialog(self), self)
        dialog.setWindowTitle('Find an event')
        dialog.resize(460, 340)
        layout = QVBoxLayout(dialog)
        query = QLineEdit(placeholderText='Search event names and locations')
        query.setAccessibleName('Search event names and locations')
        query.setMaxLength(240)
        results = QListWidget()
        results.setAccessibleName('Events found')
        layout.addWidget(query)
        layout.addWidget(results, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        visit = buttons.addButton('Show in calendar', QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)
        now = date.today()
        searchable = [(event, (event.title + ' ' + event.location).casefold())
                      for event in self.store.events.values()]

        def populate():
            results.clear()
            needle = query.text().strip().casefold()
            if needle:
                for event, searchable_text in searchable:
                    if needle not in searchable_text:
                        continue
                    horizon = 366 * 8 if event.personal and event.rule == 'FREQ=YEARLY' else 366
                    upcoming = next(occurrences(event, now, min(MAX_DAY, now + timedelta(days=horizon))), None)
                    day = (upcoming or event).span()[0]
                    item = QListWidgetItem(f'{event.title} · {QLocale().toString(_qdate(day))}')
                    item.setData(Qt.ItemDataRole.UserRole, day.isoformat())
                    results.addItem(item)
                    if results.count() >= 150:
                        break
            results.setCurrentRow(0)
            visit.setEnabled(results.count() > 0)

        def select(*_):
            item = results.currentItem()
            if item is not None:
                self.month.setSelectedDate(_qdate(date.fromisoformat(item.data(Qt.ItemDataRole.UserRole))))
                dialog.accept()

        query.textChanged.connect(populate)
        query.returnPressed.connect(select)
        results.itemActivated.connect(select)
        visit.clicked.connect(select)
        visit.setEnabled(False)
        query.setFocus()
        exec_owned_dialog(dialog)
        dialog.deleteLater()

    def show_clocks(self, enabled=True):
        self.pages.setCurrentIndex(int(enabled))
        (self.clock_button if enabled else self.calendar_button).setChecked(True)
        self.import_button.setVisible(not enabled)
        self.add_button.setVisible(not enabled)

    def closeEvent(self, event):
        if self.clock_page.alarm_job is not None:
            self.status.setText('Wait for the alarm change to finish before closing Calendar.')
            self.status.show()
            if self.pages.currentIndex() == 1:
                self.clock_page.feedback.setText(self.status.text())
            event.ignore()
            return
        if self.clock_page.active_alerts() and not themed_prompt(
            self, 'Close Calendar?', 'Closing cancels local-only timers and alarms. Saved timers and alarms stay scheduled.',
            'Close Calendar', 'Keep open'
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
        narrow = self.viewport_width() < 624 + max(0, self.theme['font_size']-14) * 15
        direction = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if self.day_layout.direction() != direction:
            self.day_layout.setDirection(direction)
        if narrow != self.compact_actions:
            self.compact_actions = narrow
            source, target = ((self.agenda_row, self.mode_row) if narrow
                              else (self.mode_row, self.agenda_row))
            source.removeWidget(self.add_button)
            if narrow:
                target.addWidget(self.add_button)
            else:
                target.insertWidget(0, self.add_button)
            self.add_button.setText('New' if narrow else 'New event')
            self.add_button.setVisible(self.pages.currentIndex() == 0)
            self.import_button.setText('' if narrow else 'Import…')
        font_size = self.theme['font_size']
        short = narrow and self.height() < 480
        inset = 6 if short else max(10, font_size // 2 + 5)
        self.update_agenda_heading(self.month.selectedDate(),short)
        self.agenda_layout.setContentsMargins(inset, inset, inset, inset)
        date_style = f'font-size: {round(font_size * (1.8 if narrow else 2.7))}px'
        if self.agenda_date.styleSheet() != date_style:
            self.agenda_date.setStyleSheet(date_style)
        self.month_label.setMinimumHeight(max(34, font_size + 18))
        label_style = f'font-size: {round(font_size * 1.2)}px'
        if self.month_label.styleSheet() != label_style:
            self.month_label.setStyleSheet(label_style)
        glyph = max(16, min(24, font_size + 2))
        self.clock_page.fit_display(font_size, self.height() < 380)
        for button in self.action_buttons:
            button.setIconSize(QSize(glyph, glyph))
            button.setMinimumSize(glyph + 18, glyph + 14)
        day_height = font_size + (5 if short else 12)
        if self.month_table is not None:
            day_height = max(day_height,self.month_table.fontMetrics().height()+2)
            self.month_table.verticalHeader().setMinimumSectionSize(day_height)
        self.month.setMinimumHeight(7 * day_height + 6)
        # Give the agenda usable space inside the scrollable page, rather than
        # forcing a window taller than small or scaled displays.
        self.event_list.setMinimumHeight(font_size * 3 + 18)

    def refresh_all(self):
        self.month.ink = self.theme
        weekend = QTextCharFormat()
        weekend.setForeground(QBrush(QColor(self.theme['muted'])))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.month.setWeekdayTextFormat(day, weekend)
        self.update_layout()
        self.refresh_month(self.month.yearShown(), self.month.monthShown())
        self.refresh_day()

    def refresh_month(self, year, month):
        heading = QLocale().toString(QDate(year, month, 1), 'MMMM yyyy')
        self.month_label.setText(heading)
        self.month_label.setAccessibleName(heading + ' · Jump to a date')
        days = self.events_by_day(year, month)
        self.month.event_days = {_qdate(day).toJulianDay() for day in days}
        self.month.updateCells()

    def events_by_day(self, year, month):
        cached = self.month_cache
        if cached and cached[0] is self.store.records and cached[1:3] == (year, month):
            return cached[3]
        first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
        days = {}
        for event in self.store.events.values():
            for instance in occurrences(event, first, last):
                start, end = instance.span()
                current, stop = max(start, first), min(end, last)
                while current <= stop:
                    days.setdefault(current, []).append(instance)
                    current += timedelta(days=1)
        self.month_cache = self.store.records, year, month, days
        return days

    def update_agenda_heading(self, selected, compact):
        self.compact_agenda_heading = compact
        self.agenda_date.setVisible(not compact)
        self.agenda_date.setText(str(selected.day()))
        pattern = 'ddd, MMM d' if compact else 'dddd\nMMMM yyyy'
        self.agenda_day.setText(QLocale().toString(selected, pattern))

    def refresh_day(self):
        selected = self.month.selectedDate()
        if not hasattr(self, 'agenda_date'):
            return
        self.update_agenda_heading(selected, getattr(self,'compact_agenda_heading',False))
        day = date(selected.year(), selected.month(), selected.day())
        rows = sorted(self.events_by_day(day.year, day.month).get(day, ()),
                      key=lambda event: (not event.all_day, event.local()[0], event.title.casefold()))
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
            if event.personal:
                item.setData(Qt.ItemDataRole.UserRole, event.key)
            item.setData(Qt.ItemDataRole.UserRole + 1, (event.title, detail))
            item.setData(Qt.ItemDataRole.UserRole + 2, event.reminder_stamp())
            item.setToolTip(f'<b>{escape(event.title)}</b><br>{escape(detail)}')
            self.event_list.addItem(item)
        self.agenda_caption.setText(('1 event' if len(rows) == 1 else f'{len(rows)} events') if rows
                                    else 'Your schedule is clear.')
        self.empty_space.setVisible(not rows)
        self.event_list.setVisible(bool(rows))
        self.event_toolbar.setVisible(bool(rows))
        self.event_actions()

    def selected_personal(self):
        item = self.event_list.currentItem()
        if item is None or not item.isSelected():
            return None
        event = self.store.records.get(item.data(Qt.ItemDataRole.UserRole))
        return event if event and event.personal else None

    def event_actions(self):
        editable = self.selected_personal() is not None
        selected = self.event_list.currentItem()
        self.edit_button.setEnabled(selected is not None and selected.isSelected())
        self.delete_button.setEnabled(editable)
        item = self.event_list.currentItem()
        stamp = item.data(Qt.ItemDataRole.UserRole + 2) if item is not None and item.isSelected() else None
        self.remind_button.setEnabled(stamp is not None and stamp > wall_clock.time())

    def remind_selected(self):
        item = self.event_list.currentItem()
        if item is None or not item.isSelected():
            return
        stamp = item.data(Qt.ItemDataRole.UserRole + 2)
        if stamp is None or stamp <= wall_clock.time():
            return
        title, _detail = item.data(Qt.ItemDataRole.UserRole + 1)
        when = QLocale().toString(QDateTime.fromSecsSinceEpoch(stamp))
        if not themed_prompt(self, 'Schedule event reminder?', f'{title}\n{when}', 'Set reminder', 'Cancel'):
            return

        def finished(message):
            self.status.setText(message)
            self.status.show()

        self.clock_page.remind_for_event(stamp, title, finished)

    def open_selected(self):
        event = self.selected_personal()
        if event:
            self.edit_event(event)
        elif (item := self.event_list.currentItem()) is not None and item.isSelected():
            title, detail = item.data(Qt.ItemDataRole.UserRole + 1)
            themed_prompt(self, 'Imported event', f'{title}\n{detail}\n\nImported events are read-only.', 'Close')

    def edit_event(self, event=None):
        dialog = style_dialog(QDialog(self), self)
        dialog.setWindowTitle('Edit event' if event else 'New event')
        layout = QFormLayout(dialog)
        title, location = QLineEdit(), QLineEdit()
        title.setMaxLength(240)
        location.setMaxLength(220)
        day = QDateEdit(self.month.selectedDate(), calendarPopup=True)
        day.setDateRange(_qdate(MIN_DAY), _qdate(MAX_DAY))
        all_day = QCheckBox('All day', checked=True)
        repeat = QComboBox()
        repeat.addItem('Does not repeat', '')
        repeat.addItem('Daily', 'FREQ=DAILY')
        repeat.addItem('Weekly', 'FREQ=WEEKLY')
        repeat.addItem('Monthly', 'FREQ=MONTHLY')
        repeat.addItem('Yearly', 'FREQ=YEARLY')
        repeat.setToolTip('Monthly and yearly repeats skip dates that do not exist.')
        start, end = QTimeEdit(QTime(9, 0)), QTimeEdit(QTime(10, 0))
        time_format = 'HH:mm' if self.theme_watch.preferences.values['clock24'] else 'h:mm AP'
        start.setDisplayFormat(time_format)
        end.setDisplayFormat(time_format)
        for label, control in (('&Title', title), ('&Location', location), ('&Date', day)):
            layout.addRow(label, control)
        layout.addRow(all_day)
        layout.addRow('&Starts', start)
        layout.addRow('&Ends', end)
        layout.addRow('&Repeat', repeat)
        if event:
            begins, ends = event.local()
            title.setText(event.title)
            location.setText(event.location)
            day.setDate(_qdate(begins if event.all_day else begins.date()))
            all_day.setChecked(event.all_day)
            repeat.setCurrentIndex(max(0, repeat.findData(event.rule)))
            if not event.all_day:
                start.setTime(QTime(begins.hour, begins.minute))
                end.setTime(QTime(ends.hour, ends.minute))
        def enable_time(checked):
            start.setEnabled(not checked)
            end.setEnabled(not checked)
        all_day.toggled.connect(enable_time)
        enable_time(all_day.isChecked())
        error_label = QLabel(wordWrap=True)
        error_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addRow(error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addRow(buttons)
        buttons.rejected.connect(dialog.reject)
        copy_button = buttons.addButton('Save as new event', QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.hide()
        def save(as_copy=False):
            try:
                self.store.save_personal(title.text(), location.text(), day.date().toPyDate(),
                                         start.time().toPyTime() if not all_day.isChecked() else None,
                                         end.time().toPyTime() if not all_day.isChecked() else None,
                                         key=event.key if event and not as_copy else None,
                                         expected=event if not as_copy else None, repeat=repeat.currentData())
            except EventConflict as error:
                error_label.setText(str(error) + ' Save as a new event to keep this draft, or Cancel to return to the updated calendar.')
                copy_button.show()
                return
            except (ValueError, OSError) as error:
                error_label.setText(str(error))
                return
            dialog.accept()
            self.status.hide()
            self.month.setSelectedDate(day.date())
        buttons.accepted.connect(save)
        copy_button.clicked.connect(lambda: save(True))
        title.setFocus()
        exec_owned_dialog(dialog)
        dialog.deleteLater()
        self.refresh_all()

    def delete_event(self):
        event = self.selected_personal()
        if not event:
            return
        message = 'Remove all occurrences of this repeating event?' if event.rule else 'Remove this event from your calendar?'
        if not themed_prompt(self, 'Delete event?', message, 'Delete event', 'Cancel'):
            return
        try:
            self.store.remove_personal(event.key, expected=event)
            self.status.hide()
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            self.status.show()
        self.refresh_all()

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

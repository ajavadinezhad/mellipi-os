from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mellipi_calendar import EventStore, occurrences, parse_ics


def calendar(*events):
    return ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n'
            + ''.join('BEGIN:VEVENT\r\n' + event + '\r\nEND:VEVENT\r\n' for event in events)
            + 'END:VCALENDAR\r\n').encode()


class CalendarImportTests(unittest.TestCase):
    def test_personal_events_preserve_imports_across_windows(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.json'
            source = Path(tmp) / 'source.ics'
            source.write_bytes(calendar('UID:imported\r\nDTSTART;VALUE=DATE:20261201\r\nSUMMARY:Imported'))
            first = EventStore(path)
            second = EventStore(path)
            first.import_path(source)
            day = date(2026, 12, 1)
            meeting = second.save_personal('Morning meeting', 'Studio', day, time(9), time(10))
            self.assertEqual(meeting.local(), (datetime(2026, 12, 1, 9), datetime(2026, 12, 1, 10)))
            self.assertEqual(len(EventStore(path).events), 2)
            with self.assertRaises(ValueError):
                first.save_personal('Invalid', '', day, time(10), time(9), key=meeting.key)
            updated = first.save_personal('Day off', '', day, key=meeting.key)
            self.assertEqual(updated.span(), (day, day))
            self.assertTrue(EventStore(path).events[meeting.key].personal)
            imported_key = next(key for key, event in first.events.items() if not event.personal)
            with self.assertRaises(ValueError):
                second.remove_personal(imported_key)
            second.remove_personal(meeting.key)
            self.assertEqual(set(EventStore(path).events), {imported_key})

    def test_unfolded_text_timezone_and_exclusive_end(self):
        changes, recurring, skipped = parse_ics(calendar(
            'UID:all-day\r\nDTSTART;VALUE=DATE:20261201\r\nDTEND;VALUE=DATE:20261203',
            'UID:timed\r\nDTSTART;TZID=America/New_York:20261201T120000\r\n'
            'DURATION:PT90M\r\nSUMMARY:Project de\r\n mo\\, winter',
            'UID:floating\r\nDTSTART:20261201T080000',
            'UID:repeats\r\nDTSTART:20261201T080000Z\r\nRRULE:FREQ=MONTHLY',
            'UID:unknown\r\nDTSTART;TZID=Missing/TimeZone:20261201T080000',
        ))
        self.assertEqual((recurring, skipped), (1, 1))
        all_day, zoned, floating = changes.values()
        self.assertEqual(all_day.span(), (date(2026, 12, 1), date(2026, 12, 2)))
        self.assertEqual(zoned.title, 'Project demo, winter')
        self.assertEqual(zoned.start, '2026-12-01T12:00:00-05:00')
        self.assertEqual(zoned.end, '2026-12-01T13:30:00-05:00')
        self.assertEqual(floating.local()[0], datetime(2026, 12, 1, 8))

    def test_import_persists_revisions_and_cancellations(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base/'event.ics'
            target = base/'local.json'
            store = EventStore(target)
            for title in ('Before', 'After'):
                source.write_bytes(calendar(f'UID:shared\r\nDTSTART:20261201T120000Z\r\nSUMMARY:{title}'))
                store.import_path(source)
                imported = list(EventStore(target).events.values())
                self.assertEqual([event.title for event in imported], [title])
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            source.write_bytes(calendar('UID:shared\r\nSTATUS:CANCELLED'))
            store.import_path(source)
            self.assertFalse(EventStore(target).events)

    def test_an_older_window_merges_changes_from_another_window(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            target = base/'events.json'
            first_window, second_window = EventStore(target), EventStore(target)
            for store, title in ((first_window, 'First'), (second_window, 'Second')):
                path = base/(title+'.ics')
                path.write_bytes(calendar(f'UID:{title}\r\nDTSTART:20261201T120000Z\r\nSUMMARY:{title}'))
                store.import_path(path)
            self.assertEqual({event.title for event in EventStore(target).events.values()}, {'First', 'Second'})

    def test_cancel_and_updates_are_ordered_by_sequence_then_stamp(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base/'source.ics'
            target = base/'events.json'

            def import_revision(sequence, stamp, status='CONFIRMED', title='Current'):
                source.write_bytes(calendar(f'UID:shared\r\nDTSTART:20261201T120000Z\r\n'
                                            f'SEQUENCE:{sequence}\r\nDTSTAMP:{stamp}\r\n'
                                            f'STATUS:{status}\r\nSUMMARY:{title}'))
                store = EventStore(target)
                store.import_path(source)
                return [event.title for event in store.events.values()]

            self.assertEqual(import_revision(4, '20261114T120000Z'), ['Current'])
            self.assertEqual(import_revision(3, '20261115T120000Z', 'CANCELLED'), ['Current'])
            self.assertEqual(import_revision(4, '20261113T120000Z', title='Old export'), ['Current'])
            self.assertEqual(import_revision(4, '20261114T120000Z', 'CANCELLED'), [])
            self.assertEqual(import_revision(4, '20261114T120000Z'), [])
            self.assertEqual(import_revision(4, '20261115T120000Z', title='Reopened'), ['Reopened'])

    def test_daily_count_and_weekly_inclusive_until(self):
        changes, unsupported, invalid = parse_ics(calendar(
            'UID:daily\r\nDTSTART;VALUE=DATE:20261201\r\nRRULE:FREQ=DAILY;INTERVAL=2;COUNT=3',
            'UID:weekly\r\nDTSTART:20261201T080000Z\r\nDURATION:PT1H\r\n'
            'RRULE:FREQ=WEEKLY;UNTIL=20261215T080000Z',
        ))
        self.assertEqual((unsupported, invalid), (0, 0))
        daily, weekly = changes.values()
        first, last = date(2026, 12, 1), date(2026, 12, 31)
        self.assertEqual([e.start for e in occurrences(daily, first, last)],
                         ['2026-12-01', '2026-12-03', '2026-12-05'])
        self.assertEqual([e.start for e in occurrences(weekly, first, last)],
                         [f'2026-12-{day}T08:00:00+00:00' for day in ('01', '08', '15')])

    def test_unbounded_rule_and_versioned_series_cancel(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            path, source = base/'events.json', base/'event.ics'
            rule = 'UID:shared\r\nSEQUENCE:1\r\nDTSTART;VALUE=DATE:19000101\r\nRRULE:FREQ=DAILY'
            source.write_bytes(calendar(rule))
            EventStore(path).import_path(source)
            store = EventStore(path)
            self.assertEqual(len(store.records), 1)
            self.assertTrue(next(occurrences(next(iter(store.events.values())),
                                             date(2200, 12, 30), date(2200, 12, 30))))
            source.write_bytes(calendar('UID:shared\r\nSEQUENCE:2\r\nSTATUS:CANCELLED'))
            store.import_path(source)
            source.write_bytes(calendar(rule))
            EventStore(path).import_path(source)
            self.assertFalse(EventStore(path).events)

    def test_unsupported_exception_never_imports_a_partial_series(self):
        changes, unsupported, invalid = parse_ics(calendar(
            'UID:weekly\r\nDTSTART:20261201T080000Z\r\nRRULE:FREQ=WEEKLY',
            'UID:weekly\r\nRECURRENCE-ID:20261208T080000Z\r\nSTATUS:CANCELLED',
            'UID:timezone\r\nDTSTART;TZID=America/New_York:20261201T080000\r\nRRULE:FREQ=DAILY',
        ))
        self.assertEqual((changes, unsupported, invalid), ({}, 2, 0))

"""Small persisted alarm queue; systemd's user timers deliver without Calendar."""
import argparse
from contextlib import contextmanager
import fcntl
from html import escape
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from installed_launcher import user_environment

MAX_ALARMS = 16
MAX_STAMP = 4_102_444_799
MAX_BYTES = 32768
ALARM_FILE = 'calendar-alarms.json'
ID = re.compile(r'[a-f0-9]{32}')
FIRE_BACKOFF = (.2, .4, .8, 1.6, 3.2)


class AlarmBusy(ValueError):
    pass


def queue_path():
    return Path(user_environment()['ORBIT_DATA']) / ALARM_FILE


def alarm_time(value):
    return value['time'] if isinstance(value, dict) else value


def alarm_label(value):
    return value.get('label', '') if isinstance(value, dict) else ''

def is_countdown(value):
    return isinstance(value, dict) and value.get('kind') == 'countdown'


def valid_alarm(value):
    if is_countdown(value):
        return (set(value) == {'time', 'kind'} and type(value['time']) is int
                and 0 < value['time'] <= MAX_STAMP)
    if isinstance(value, dict) and (set(value) != {'time', 'label'} or
            not isinstance(value['label'], str) or not 0 < len(value['label']) <= 240 or
            not value['label'].isprintable()):
        return False
    stamp = alarm_time(value)
    return type(stamp) is int and 0 < stamp <= MAX_STAMP


def read_queue(path):
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    with os.fdopen(handle, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Untrusted alarm queue')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Alarm queue is too large')
    rows = json.loads(raw)
    if (not isinstance(rows, dict) or len(rows) > MAX_ALARMS or
            any(not ID.fullmatch(key) or not valid_alarm(value)
                for key, value in rows.items())):
        raise ValueError('Invalid alarm queue')
    return rows


@contextmanager
def locked_queue(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = os.open(path.with_suffix('.lock'),
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(handle, 'rb+') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Untrusted alarm lock')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlarmBusy('Calendar alarms are busy. Try again.') from None
        yield read_queue(path)


def write_queue(path, rows):
    handle, name = tempfile.mkstemp(dir=path.parent, prefix='.alarms-')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(rows, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def run_command(args):
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=3, check=False).returncode == 0


def schedule(path, key, stamp, run=run_command, *, retry_after_login=False):
    unit = 'mellipi-calendar-alarm-' + key
    command = ['/usr/bin/systemd-run', '--user', '--quiet', '--collect', '--unit=' + unit,
               '--on-active=8s' if retry_after_login else '--on-calendar=@' + str(stamp),
               '--timer-property=AccuracySec=1s',
               '--setenv=ORBIT_DATA=' + str(path.parent),
               '/usr/bin/python3', str(Path(__file__).resolve()), 'fire', key]
    return run(command) or run(['/usr/bin/systemctl', '--user', 'is-active', '--quiet', unit + '.timer'])


def queue_alarm(path, stamp, *, label='', countdown=False, now=time.time, run=run_command):
    if type(stamp) is not int or not now() < stamp <= MAX_STAMP:
        raise ValueError('Choose a supported time in the future.')
    label = ''.join(char for char in label if char.isprintable()).strip()[:240]
    entry = {'time': stamp, 'kind': 'countdown'} if countdown else ({'time': stamp, 'label': label} if label else stamp)
    key = uuid4().hex
    with locked_queue(path) as rows:
        if countdown and any(is_countdown(value) for value in rows.values()):
            raise ValueError('A countdown is already running.')
        if len(rows) >= MAX_ALARMS:
            raise ValueError(f'Remove an alarm first. Up to {MAX_ALARMS} alarms are supported.')
        if entry in rows.values():
            raise ValueError('An alarm is already scheduled at this time.')
        rows[key] = entry
        write_queue(path, rows)
        try:
            if not schedule(path, key, stamp, run):
                raise OSError('Could not schedule the alarm.')
        except (OSError, subprocess.TimeoutExpired):
            del rows[key]
            write_queue(path, rows)
            raise
    return key


def cancel_alarm(path, key, *, run=run_command):
    if not ID.fullmatch(key):
        raise ValueError('Invalid alarm identifier')
    with locked_queue(path) as rows:
        if key not in rows:
            return False
        del rows[key]
        write_queue(path, rows)
    # Even if systemd is unavailable, fire() consults the queue before notifying.
    try:
        run(['/usr/bin/systemctl', '--user', 'stop', 'mellipi-calendar-alarm-' + key + '.timer'])
    except (OSError, subprocess.TimeoutExpired):
        pass
    return True


def fire(path, key, *, now=time.time, run=run_command, wait=time.sleep):
    for delay in (0, *FIRE_BACKOFF):
        if delay:
            wait(delay)
        try:
            result = _fire_once(path, key, now=now, run=run)
        except AlarmBusy:
            continue
        if result is not None:
            return result
    raise OSError('Could not deliver alarm after retrying. It remains scheduled for recovery at sign-in.')


def _fire_once(path, key, *, now, run):
    with locked_queue(path) as rows:
        entry = rows.get(key)
        if entry is None or (stamp := alarm_time(entry)) > now() + 1:
            return False
        label = alarm_label(entry)
        title = ('Missed reminder' if now() - stamp > 90 else 'Event reminder') if label else (
            'Missed alarm' if now() - stamp > 90 else 'Alarm')
        if is_countdown(entry):
            title = 'Timer finished'
        # Remove an alarm only when the notification server accepts delivery.
        if not run(['/usr/bin/notify-send', '-a', 'Mellipi Calendar', '--', title, *([escape(label)] if label else [])]):
            # A failed notifier may be starting. Retry only explicit failures,
            # not a timeout or a queue write failure after successful delivery.
            return None
        del rows[key]
        write_queue(path, rows)
        return True


def restore(path, *, now=time.time, run=run_command, login=False):
    for key, value in read_queue(path).items():
        stamp = alarm_time(value)
        try:
            if stamp <= now():
                if login:
                    schedule(path, key, stamp, run, retry_after_login=True)
                else:
                    fire(path, key, now=now, run=run)
            else:
                schedule(path, key, stamp, run)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue


def main():
    command = argparse.ArgumentParser()
    action = command.add_subparsers(dest='action', required=True)
    add = action.add_parser('add')
    add.add_argument('stamp', type=int)
    add.add_argument('--label', default='')
    add.add_argument('--countdown', action='store_true')
    for name in ('cancel', 'fire'):
        action.add_parser(name).add_argument('key')
    action.add_parser('restore').add_argument('--login', action='store_true')
    args = command.parse_args()
    path = queue_path()
    try:
        if args.action == 'add':
            queue_alarm(path, args.stamp, label=args.label, countdown=args.countdown)
        elif args.action == 'cancel':
            cancel_alarm(path, args.key)
        elif args.action == 'fire':
            fire(path, args.key)
        else:
            restore(path, login=args.login)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error)[:240], file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

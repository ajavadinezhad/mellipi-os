"""Small event-only launcher history: desktop IDs, weighted counts and timestamps.

The caller supplies the current application catalog. No titles, document paths,
commands, or application content are recorded. Focus scores are debounced in
memory; changed interaction timestamps still keep Recent ordering accurate.
"""
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

LIMIT = 512
MAX_FILE_BYTES = 1024 * 1024
WEIGHTS = {'launch': 2, 'focus': 1}


def valid_id(value):
    return isinstance(value, str) and len(value) <= 256 and re.fullmatch(r'[\w.+-]+\.desktop', value) is not None


def name_key(app):
    name = app.get('name')
    ident = app.get('id', '')
    return (name.casefold() if isinstance(name, str) else str(ident).casefold(), str(ident))


class AppUsage:
    def __init__(self, path, app_ids=(), clock=None, focus_debounce=30):
        self.path = Path(path)
        self.clock = clock or time.time
        if not isinstance(focus_debounce, (int, float)) or not math.isfinite(focus_debounce) or focus_debounce < 0:
            raise ValueError('Invalid focus debounce')
        self.focus_debounce = float(focus_debounce)
        self.last_error = ''
        self._focus_times = {}
        self._records = {}
        self.set_catalog(app_ids)
        self._load()

    @property
    def records(self):
        return {ident: dict(row) for ident, row in self._records.items()}

    def set_catalog(self, apps_or_ids):
        if isinstance(apps_or_ids, str):
            apps_or_ids = [apps_or_ids]
        self._allowed = frozenset(ident for value in apps_or_ids for ident in [value.get('id') if isinstance(value, dict) else value] if valid_id(ident))
        if hasattr(self, '_focus_times'):
            self._focus_times = {ident: stamp for ident, stamp in self._focus_times.items() if ident in self._allowed}

    @staticmethod
    def _bounded(records):
        chosen = sorted(records, key=lambda ident: (-records[ident]['lastUsed'], -records[ident]['count'], ident))[:LIMIT]
        return {ident: records[ident] for ident in chosen}

    def _load(self):
        try:
            with self.path.open('rb') as source:
                data = source.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                return
            payload = json.loads(data)
            if not isinstance(payload, dict) or type(payload.get('version')) is not int or payload.get('version') != 1 or not isinstance(payload.get('apps'), dict):
                return
            records = {}
            for ident, values in payload['apps'].items():
                if not valid_id(ident) or not isinstance(values, dict):
                    continue
                count, stamp = values.get('count'), values.get('lastUsed')
                if type(count) is not int or not 0 <= count <= 1_000_000_000:
                    continue
                if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= stamp <= 1_000_000_000_000:
                    continue
                records[ident] = {'count': count, 'lastUsed': float(stamp)}
            self._records = self._bounded(records)
        except (OSError, ValueError, UnicodeError):
            # Corrupt or unavailable history must never break the launcher.
            return

    def _commit(self, records):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix='.orbit-usage-', dir=self.path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump({'version': 1, 'apps': records}, output, ensure_ascii=False, separators=(',', ':'))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            self.last_error = ''
            return True
        except OSError as error:
            self.last_error = str(error)[:200]
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def record(self, app_id, interaction='launch'):
        """Count one known app interaction; return False if ignored or unsaved.

        Launches have weight two and counted focus events weight one. Focuses
        inside the score debounce still update recency without adding weight. A failed
        history write leaves the previous in-memory and on-disk state intact;
        last_error can be inspected without interrupting an app launch.
        """
        if not valid_id(app_id) or app_id not in self._allowed or not isinstance(interaction, str) or interaction not in WEIGHTS:
            return False
        try:
            now = float(self.clock())
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(now) or not 0 <= now <= 1_000_000_000_000:
            return False
        weight = WEIGHTS[interaction]
        if interaction == 'focus':
            previous_focus = self._focus_times.get(app_id)
            if previous_focus is not None and 0 <= now - previous_focus < self.focus_debounce:
                weight = 0
            else:
                self._focus_times[app_id] = now
                if len(self._focus_times) > LIMIT:
                    recent = sorted(self._focus_times, key=lambda ident: (-self._focus_times[ident], ident))[:LIMIT]
                    self._focus_times = {ident: self._focus_times[ident] for ident in recent}
        previous = self._records.get(app_id, {'count': 0, 'lastUsed': 0})
        if weight == 0 and previous['lastUsed'] == now:
            return False
        records = {**self._records, app_id: {'count': min(1_000_000_000, previous['count'] + weight), 'lastUsed': now}}
        records = self._bounded(records)
        if not self._commit(records):
            return False
        self._records = records
        return True

    def rank(self, apps, mode='frequent'):
        """Return a new catalog list with deterministic alphabetical tie breaks."""
        if mode not in ('frequent', 'recent', 'name'):
            raise ValueError('Unknown launcher sort mode')
        def key(app):
            row = self._records.get(app.get('id'), {'count': 0, 'lastUsed': 0})
            return ((-row['count'],) if mode == 'frequent' else (-row['lastUsed'],) if mode == 'recent' else ()) + name_key(app)
        return sorted(apps, key=key)

    def reset(self):
        """Clear history only after the empty state is saved successfully."""
        if not self._commit({}):
            return False
        self._records.clear()
        self._focus_times.clear()
        return True

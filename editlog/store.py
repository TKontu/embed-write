"""Append-only local SQLite store for edit-log entries (EL-03).

The edit log is private data: callers place the file under a gitignored path.
"""

import json
import sqlite3

from editlog.schema import EditLogEntry, validate_entry

_COLUMNS = EditLogEntry.field_names()
_SCHEMA = (
    'CREATE TABLE IF NOT EXISTS entries ('
    'id INTEGER PRIMARY KEY AUTOINCREMENT, '
    + ', '.join('%s TEXT NOT NULL' % c for c in _COLUMNS) + ')'
)


class EditLogStore:
    """Append-only store: append, get, iter_entries, count. No update/delete."""

    iter_batch = 256

    def __init__(self, path):
        path = str(path)
        if path != ':memory:' and (path.startswith('file:') or '://' in path):
            raise ValueError('path: local file path or :memory: only')
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.execute(_SCHEMA)

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def append(self, entry):
        """Validate, then insert in its own transaction; return the row id."""
        validate_entry(entry)
        values = [json.dumps(entry.panel_values, allow_nan=False, sort_keys=True)
                  if c == 'panel_values' else getattr(entry, c) for c in _COLUMNS]
        sql = 'INSERT INTO entries (%s) VALUES (%s)' % (
            ', '.join(_COLUMNS), ', '.join('?' * len(_COLUMNS)))
        with self._conn:
            self._conn.execute('BEGIN')
            cur = self._conn.execute(sql, values)
        return cur.lastrowid

    @staticmethod
    def _entry(row):
        data = dict(zip(_COLUMNS, row))
        data['panel_values'] = json.loads(data['panel_values'])
        return EditLogEntry(**data)

    def get(self, entry_id):
        row = self._conn.execute(
            'SELECT %s FROM entries WHERE id = ?' % ', '.join(_COLUMNS),
            (entry_id,)).fetchone()
        return None if row is None else self._entry(row)

    def iter_entries(self):
        """Yield (id, entry) in id order, fetching iter_batch rows at a time."""
        cur = self._conn.execute(
            'SELECT id, %s FROM entries ORDER BY id' % ', '.join(_COLUMNS))
        try:
            while True:
                rows = cur.fetchmany(self.iter_batch)
                if not rows:
                    return
                for row in rows:
                    yield row[0], self._entry(row[1:])
        finally:
            cur.close()

    def count(self):
        return self._conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0]

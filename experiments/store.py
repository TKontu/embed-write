"""Local gate metrics; unwired by design until EV-03 and gate modules consume them.

Values retain their population, metric and version/commit reference. Interpretation
and attribution of who built a measurement belong to the gate/report, not this store.
"""
from itertools import islice
import math
import sqlite3

_FIELDS = ('gate', 'arm', 'metric', 'value', 'n', 'timestamp', 'commit',
           'modelVersion', 'inventoryVersion')
_COLUMNS = ', '.join('"' + name + '"' for name in _FIELDS) + ', lo, hi'
_INSERT = 'INSERT INTO results (' + _COLUMNS + ') VALUES (' + ', '.join(['?'] * 11) + ')'


class ResultStore:
    """A local SQLite store. Call close() when finished."""

    def __init__(self, path):
        self._connection = sqlite3.connect(path)
        self._connection.execute('''CREATE TABLE IF NOT EXISTS results (
            gate TEXT NOT NULL, arm TEXT NOT NULL, metric TEXT NOT NULL,
            value REAL NOT NULL, n INTEGER NOT NULL, timestamp TEXT NOT NULL,
            "commit" TEXT NOT NULL, modelVersion TEXT NOT NULL,
            inventoryVersion TEXT NOT NULL, lo REAL, hi REAL
        )''')
        self._connection.commit()

    def close(self):
        self._connection.close()

    @staticmethod
    def _values(record):
        missing = set(_FIELDS + ('interval',)) - record.keys()
        if missing:
            raise ValueError('missing required fields: ' + ', '.join(sorted(missing)))
        n = record['n']
        if type(n) is not int or not 0 < n <= 2**63 - 1:
            raise ValueError('n must be a positive SQLite integer')
        value = record['value']
        def finite(number):
            return type(number) in (int, float) and math.isfinite(number)
        if not finite(value):
            raise ValueError('value must be a finite number')
        interval = record['interval']
        bounds = (None, None)
        if interval is not None:
            if (not isinstance(interval, (tuple, list)) or len(interval) != 2
                    or not all(finite(x) for x in interval)
                    or not interval[0] <= value <= interval[1]):
                raise ValueError('interval must satisfy lo <= value <= hi, or be None')
            bounds = tuple(interval)
        return tuple(record[k] for k in _FIELDS) + bounds

    def add(self, record):
        values = self._values(record)
        with self._connection:
            self._connection.execute(_INSERT, values)

    def add_many(self, records, batch_size=500):
        """Commit at most batch_size rows at a time, retaining completed batches.

        Invalid records or a failing input iterator discard the current batch.
        Memory and each transaction are bounded by batch_size.
        """
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError('batch_size must be a positive integer')
        records = iter(records)
        while True:
            batch = [self._values(record) for record in islice(records, batch_size)]
            if not batch:
                return
            with self._connection:
                self._connection.executemany(_INSERT, batch)

    def query(self, gate=None, arm=None, metric=None):
        """Yield records in insertion order; close an abandoned iterator promptly."""
        filters = [(key, value) for key, value in
                   (('gate', gate), ('arm', arm), ('metric', metric)) if value is not None]
        where = ' WHERE ' + ' AND '.join(key + ' = ?' for key, _ in filters) if filters else ''
        cursor = self._connection.execute(
            'SELECT ' + _COLUMNS + ' FROM results' + where + ' ORDER BY rowid',
            [value for _, value in filters])
        try:
            for row in cursor:
                record = dict(zip(_FIELDS, row[:9]))
                record['interval'] = None if row[9] is None else (row[9], row[10])
                yield record
        finally:
            cursor.close()

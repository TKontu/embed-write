"""Offline SQLite result-store acceptance tests using synthetic metrics."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


def record(**changes):
    result = dict(gate='G-00', arm='baseline', metric='accuracy', value=0.5,
                  n=10, interval=(0.4, 0.6), timestamp='2026-11-23T00:00:00Z',
                  commit='synthetic-commit', modelVersion='fixture-v1',
                  inventoryVersion='fixture-v1')
    result.update(changes)
    return result


class ResultStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'results.sqlite'

    def store(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.store'),
                             'EV-02 result store is not implemented')
        from experiments.store import ResultStore
        store = ResultStore(self.path)
        self.addCleanup(store.close)
        return store

    def test_round_trip_survives_reopen(self):
        store = self.store()
        store.add(record())
        store.close()
        self.assertEqual(list(self.store().query()), [record()])

    def test_rejects_each_missing_field(self):
        store = self.store()
        for field in record():
            with self.subTest(field=field):
                incomplete = record()
                del incomplete[field]
                with self.assertRaises(ValueError):
                    store.add(incomplete)
        self.assertEqual(list(store.query()), [])

    def test_rejects_invalid_population_and_interval(self):
        store = self.store()
        for n in (0, -1, True, 1.5, '10', None):
            with self.subTest(n=n), self.assertRaises(ValueError):
                store.add(record(n=n))
        for interval in ((0.6, 0.7), (0.1, 0.4), (0.6, 0.4), (), (0, 1, 2),
                         ('low', 'high'), (float('nan'), 1)):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                store.add(record(interval=interval))
        for value in (None, True, '0.5', float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                store.add(record(value=value, interval=None))
        self.assertEqual(list(store.query()), [])

    def test_explicit_none_and_interval_endpoints(self):
        store = self.store()
        for interval in (None, (0.5, 0.5), [0.4, 0.5]):
            store.add(record(interval=interval))
        self.assertEqual([r['interval'] for r in store.query()],
                         [None, (0.5, 0.5), (0.4, 0.5)])

    def test_query_filters_and_literal_values(self):
        store = self.store()
        rows = [record(), record(gate='G-01'), record(arm='other'),
                record(metric='loss'), record(gate="' OR 1=1 --")]
        for row in rows:
            store.add(row)
        for filters in ({'gate': 'G-00'}, {'arm': 'other'}, {'metric': 'loss'},
                        {'gate': 'G-00', 'arm': 'baseline', 'metric': 'accuracy'},
                        {'gate': "' OR 1=1 --"}, {'gate': ''}):
            with self.subTest(filters=filters):
                self.assertEqual(list(store.query(**filters)),
                                 [r for r in rows if all(r[k] == v for k, v in filters.items())])

    def test_bulk_commits_are_bounded_and_consumption_is_incremental(self):
        import sqlite3
        for size in (None, 137):
            with self.subTest(batch_size=size):
                store = self.store()
                connection = sqlite3.connect(self.path)
                self.addCleanup(connection.close)
                connection.execute('DELETE FROM results')
                connection.commit()
                batch = 500 if size is None else size
                def records():
                    for i in range(10_000):
                        if i % batch == 0:
                            self.assertEqual(connection.execute(
                                'SELECT count(*) FROM results').fetchone()[0], i)
                        yield record()
                self.assertTrue(callable(getattr(store, 'add_many', None)),
                                'bounded bulk insertion is missing')
                if size is None:
                    store.add_many(records())
                else:
                    store.add_many(records(), batch_size=size)
                self.assertEqual(connection.execute(
                    'SELECT count(*) FROM results').fetchone()[0], 10_000)

    def test_bulk_failure_rolls_back_current_batch_only(self):
        store = self.store()
        self.assertTrue(callable(getattr(store, 'add_many', None)))
        with self.assertRaises(ValueError):
            store.add_many(iter([record(), record(), record(), record(n=0)]), batch_size=2)
        self.assertEqual(len(list(store.query())), 2)
        store.add(record())
        self.assertEqual(len(list(store.query())), 3)

    def test_invalid_batch_size_does_not_consume_input(self):
        store = self.store()
        self.assertTrue(callable(getattr(store, 'add_many', None)))
        def untouched():
            self.fail('invalid batch size consumed input')
            yield record()
        for size in (0, -1, True, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                store.add_many(untouched(), batch_size=size)

    def test_query_reads_incrementally(self):
        store = self.store()
        for _ in range(100):
            store.add(record())
        reads = []
        store._connection.row_factory = lambda cursor, row: (reads.append(1) or row)
        rows = store.query()
        self.assertIs(iter(rows), rows)
        self.assertEqual(reads, [])
        self.assertEqual(next(rows), record())
        self.assertEqual(len(reads), 1)
        rows.close()

    def test_append_only_api_has_no_delete_update_or_replace(self):
        from experiments.store import ResultStore
        public = {name for name in dir(ResultStore) if not name.startswith('_')}
        for word in ('delete', 'remove', 'update', 'replace', 'drop', 'clear',
                     'upsert', 'truncate', 'purge', 'edit'):
            self.assertEqual([n for n in public if word in n.lower()], [], word)
        self.assertEqual(public, {'add', 'add_many', 'close', 'query'})

    def test_zero_negative_and_crossing_intervals_round_trip(self):
        rows = [record(value=0, interval=(0, 0)),
                record(value=0.0, interval=(-0.1, 0.1)),
                record(value=-0.05, interval=(-0.2, 0.1)),
                record(value=-0.3, interval=(-0.5, -0.1)),
                record(value=-2, interval=None)]
        store = self.store()
        store.add_many(rows)
        store.close()
        self.assertEqual(list(self.store().query(gate='G-00')), rows)

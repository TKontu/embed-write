import os
import sqlite3
import tempfile
import types
import unittest

from editlog.schema import EditLogEntry
from editlog.store import EditLogStore


def make(i=0, **over):
    fields = dict(genre='g', section_type='s', move='m', original_text='oä',
                  candidate='c%d' % i, final_text='f', action='accept',
                  panel_values={'n': i, 'nested': {'a': [1, 2.5, None]}},
                  generation_run_id='run-%d' % i,
                  timestamp='2026-11-24T10:00:00+00:00')
    fields.update(over)
    return EditLogEntry(**fields)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'edit_log.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_and_reopen(self):
        store = EditLogStore(self.path)
        entry = make(1)
        entry_id = store.append(entry)
        self.assertEqual(store.get(entry_id), entry)
        store.close()
        reopened = EditLogStore(self.path)
        self.assertEqual(reopened.get(entry_id), entry)
        self.assertEqual(reopened.count(), 1)
        self.assertIsNone(reopened.get(entry_id + 99))
        reopened.close()

    def test_memory(self):
        store = EditLogStore(':memory:')
        store.append(make())
        self.assertEqual(store.count(), 1)

    def test_iter_entries_streams(self):
        store = EditLogStore(self.path)
        ids = [store.append(make(i)) for i in range(5)]
        it = store.iter_entries()
        self.assertIsInstance(it, types.GeneratorType)
        first = next(it)
        self.assertEqual(first, (ids[0], make(0)))
        rest = list(it)
        self.assertEqual([e for _, e in rest], [make(i) for i in range(1, 5)])
        self.assertGreater(store.iter_batch, 0)

    def test_invalid_rejected_before_write(self):
        store = EditLogStore(self.path)
        with self.assertRaises(ValueError):
            store.append(make(action='bogus'))
        self.assertEqual(store.count(), 0)

    def test_each_append_committed(self):
        store = EditLogStore(self.path)
        store.append(make())
        other = sqlite3.connect(self.path)
        self.assertEqual(other.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 1)
        other.close()

    def test_append_only_api(self):
        public = {n for n in dir(EditLogStore) if not n.startswith('_')}
        for word in ('update', 'delete', 'remove', 'replace', 'edit', 'clear', 'truncate'):
            self.assertFalse([n for n in public if word in n], word)

    def test_rejects_uri_and_network_paths(self):
        for bad in ('file:x.db?mode=memory', 'http://host/db'):
            with self.assertRaises(ValueError):
                EditLogStore(bad)


if __name__ == '__main__':
    unittest.main()

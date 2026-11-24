import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from editlog import export as export_mod
from editlog.export import export_jsonl, main
from editlog.schema import EditLogEntry
from editlog.store import EditLogStore


def make(i=0, **over):
    fields = dict(genre='g', section_type='s', move='m', original_text='oä\n"q"',
                  candidate='c%d' % i, final_text='f', action='accept',
                  panel_values={'n': i, 'nested': {'a': [1, 2.5, None]}},
                  generation_run_id='run-%d' % i,
                  timestamp='2026-11-24T10:00:00+00:00')
    fields.update(over)
    return EditLogEntry(**fields)


def parse(path):
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh]


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'log.sqlite')
        self.out = os.path.join(self.tmp.name, 'out.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_in_id_order(self):
        store = EditLogStore(':memory:')
        store.iter_batch = 2
        entries = [make(i, action=a) for i, a in
                   enumerate(['accept', 'edit', 'reject', 'accept', 'edit'])]
        ids = [store.append(e) for e in entries]
        self.assertEqual(export_jsonl(store, self.out), 5)
        rows = parse(self.out)
        self.assertEqual([r['id'] for r in rows], ids)
        for row, entry in zip(rows, entries):
            row_id = row.pop('id')
            self.assertEqual(EditLogEntry(**row), entry)
            self.assertEqual(store.get(row_id), entry)
        self.assertEqual(set(rows[0]), set(EditLogEntry.field_names()))

    def test_empty_store(self):
        store = EditLogStore(':memory:')
        self.assertEqual(export_jsonl(store, self.out), 0)
        with open(self.out, 'rb') as fh:
            self.assertEqual(fh.read(), b'')

    def test_mode_0600(self):
        old = os.umask(0)
        try:
            export_jsonl(EditLogStore(':memory:'), self.out)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o600)

    def test_refuses_overwrite_unless_force(self):
        with open(self.out, 'w') as fh:
            fh.write('keep')
        store = EditLogStore(':memory:')
        store.append(make(1))
        with self.assertRaises(FileExistsError):
            export_jsonl(store, self.out)
        with open(self.out) as fh:
            self.assertEqual(fh.read(), 'keep')
        self.assertEqual(export_jsonl(store, self.out, force=True), 1)
        self.assertEqual(len(parse(self.out)), 1)

    def test_failure_leaves_no_partial_file(self):
        store = EditLogStore(':memory:')
        store.append(make(1))
        store.append(make(2))

        def boom():
            yield 1, make(1)
            raise RuntimeError('mid-stream')
        with mock.patch.object(store, 'iter_entries', boom):
            with self.assertRaises(RuntimeError):
                export_jsonl(store, self.out)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_streams_through_iter_entries(self):
        store = EditLogStore(':memory:')
        store.append(make(1))
        calls = []
        real = store.iter_entries

        def spy():
            calls.append(1)
            return real()
        with mock.patch.object(store, 'iter_entries', spy):
            export_jsonl(store, self.out)
        self.assertEqual(calls, [1])

    def test_cli(self):
        with EditLogStore(self.db) as store:
            store.append(make(1))
        self.assertEqual(main([self.db, self.out]), 0)
        self.assertEqual(len(parse(self.out)), 1)
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertNotEqual(main([self.db, self.out]), 0)
        self.assertIn('--force', err.getvalue())
        self.assertEqual(main([self.db, self.out, '--force']), 0)

    def test_cli_missing_db_not_created(self):
        missing = os.path.join(self.tmp.name, 'nope.sqlite')
        with redirect_stderr(io.StringIO()):
            self.assertNotEqual(main([missing, self.out]), 0)
        self.assertFalse(os.path.exists(missing))
        self.assertFalse(os.path.exists(self.out))


if __name__ == '__main__':
    unittest.main()

import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from editlog.store import EditLogStore
from test_editlog_export import make


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'log.sqlite'
        self.out = Path(self.tmp.name) / 'export.jsonl'
        with EditLogStore(self.db) as store:
            store.append(make())

    def cli(self, *args, answer=''):
        return subprocess.run(
            [sys.executable, '-m', 'editlog.delete', str(self.db), *args],
            input=answer, capture_output=True, text=True)

    def test_yes_deletes_whole_log_and_offers_export(self):
        result = self.cli('--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--export', result.stdout)
        self.assertFalse(self.db.exists())

    def test_delete_removes_sidecars_and_preserves_unrelated_files(self):
        paths = [Path(str(self.db) + suffix)
                 for suffix in ('-wal', '-shm', '-journal')]
        for path in paths:
            path.write_bytes(b'synthetic sidecar')
        self.out.write_text('keep')
        importlib.import_module('editlog.delete').delete_log(self.db)
        self.assertFalse(self.db.exists())
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(self.out.read_text(), 'keep')

    def test_missing_database_raises_and_keeps_orphan_sidecar(self):
        self.db.unlink()
        sidecar = Path(str(self.db) + '-wal')
        sidecar.write_bytes(b'keep')
        with self.assertRaises(FileNotFoundError):
            importlib.import_module('editlog.delete').delete_log(self.db)
        self.assertTrue(sidecar.exists())

    def test_uri_network_and_memory_paths_refused(self):
        for path in ('file:log.sqlite', 'https://host/log', '//host/log',
                     '\\\\host\\log', ':memory:'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                importlib.import_module('editlog.delete').delete_log(path)

    def test_declined_confirmation_keeps_database_unchanged(self):
        before = self.db.read_bytes()
        for answer in ('no\n', 'yes\n', ''):
            result = self.cli(answer=answer)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('DELETE', result.stdout)
            self.assertEqual(self.db.read_bytes(), before)

    def test_typed_confirmation_deletes(self):
        result = self.cli(answer='DELETE\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.db.exists())

    def test_export_then_delete(self):
        result = self.cli('--export', str(self.out), '--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.db.exists())
        row = json.loads(self.out.read_text())
        self.assertEqual(row['id'], 1)
        self.assertEqual(row['original_text'], make().original_text)

    def test_failed_export_aborts_deletion(self):
        self.out.write_text('keep')
        before = self.db.read_bytes()
        result = self.cli('--export', str(self.out), '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.out.read_text(), 'keep')

    def test_missing_database_is_not_created_by_export(self):
        self.db.unlink()
        result = self.cli('--export', str(self.out), '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.db.exists())
        self.assertFalse(self.out.exists())

    def test_export_cannot_be_deleted_as_a_sidecar(self):
        result = self.cli('--export', str(self.db) + '-wal', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.db.exists())

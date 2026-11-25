"""Synthetic, offline CA-01/CA-02 acceptance checks."""
from dataclasses import replace
import importlib.util
import inspect
import json
import struct
import tempfile
import unittest

from service.vectors import Level, LevelVector

try:
    import lmdb
except ImportError:
    lmdb = None


@unittest.skipIf(lmdb is None, 'lmdb is not importable; install requirements.txt in .venv')
class VectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('service.vector_store'),
                             'CA-01 vector store has not been implemented')
        from service.vector_store import VectorKey, VectorStore
        self.VectorStore = VectorStore
        self.key = VectorKey('model', 'v1', Level.SENTENCE, 'hash', 2)
        self.vector = LevelVector(Level.SENTENCE, (1.25, -2.5))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.name

    def capped_store(self, cap):
        self.assertIn('max_bytes', inspect.signature(self.VectorStore).parameters,
                      'CA-03 requires an optional byte cap')
        return self.VectorStore(self.path, max_bytes=cap)

    def entry_size(self, key):
        header = json.dumps([key.level.value, key.dims], separators=(',', ':'))
        return len(key.encode()) + len(header.encode('ascii')) + 1 + 8 * key.dims

    def test_cap_boundary_evicts_oldest_across_keyspaces(self):
        newer = replace(self.key, model_version='v2')
        newest = replace(self.key, model_version='v3')
        size = self.entry_size(self.key)
        with self.capped_store(2 * size) as store:
            self.assertEqual((len(store), store.size_bytes()), (0, 0))
            store.put(self.key, self.vector)
            store.put(newer, self.vector)
            self.assertEqual((len(store), store.size_bytes()), (2, 2 * size))
            self.assertEqual(store.get(self.key), self.vector)
            store.put(newest, self.vector)
            self.assertIsNone(store.get(self.key))
            self.assertEqual(list(store.keys('model', 'v1')), [])
            self.assertEqual(store.get(newer), self.vector)
            self.assertEqual(store.get(newest), self.vector)
            self.assertEqual((len(store), store.size_bytes()), (2, 2 * size))

    def test_oversized_entry_preserves_store_and_order(self):
        import service.vector_store as module
        size = self.entry_size(self.key)
        with self.capped_store(size) as store:
            store.put(self.key, self.vector)
            before = store._env.info()['last_txnid']
            large = replace(self.key, dims=100)
            with self.assertRaises(module.CapacityError):
                store.put(large, LevelVector(large.level, (1,) * large.dims))
            self.assertEqual(store._env.info()['last_txnid'], before)
            self.assertEqual((len(store), store.size_bytes()), (1, size))
            self.assertEqual(list(store.keys('model', 'v1')), [self.key])
            self.assertEqual(store.get(self.key), self.vector)
            self.assertIsNone(store.get(large))

    def test_identical_reput_and_reads_do_not_refresh_fifo_after_reopen(self):
        newer = replace(self.key, content_hash='new1')
        newest = replace(self.key, content_hash='new2')
        size = self.entry_size(self.key)
        with self.capped_store(2 * size) as store:
            store.put(self.key, self.vector)
            store.put(newer, self.vector)
            before = store._env.info()['last_txnid']
            store.put(self.key, self.vector)
            store.get(self.key)
            self.assertEqual(store._env.info()['last_txnid'], before)
            self.assertEqual(store.size_bytes(), 2 * size)
        with self.capped_store(2 * size) as store:
            self.assertEqual((len(store), store.size_bytes()), (2, 2 * size))
            store.put(newest, self.vector)
            self.assertIsNone(store.get(self.key))
            self.assertEqual(store.get(newer), self.vector)
            # An evicted key can be inserted with a different value.
            changed = LevelVector(self.key.level, (8, 9))
            store.put(self.key, changed)
            self.assertIsNone(store.get(newer))
            self.assertEqual(store.get(self.key), changed)
            self.assertEqual(set(store.keys('model', 'v1')), {self.key, newest})

    def test_large_insert_evicts_multiple_entries(self):
        size = self.entry_size(self.key)
        large = replace(self.key, dims=10)
        with self.capped_store(3 * size) as store:
            for suffix in ('hash', 'new1', 'new2'):
                store.put(replace(self.key, content_hash=suffix), self.vector)
            store.put(large, LevelVector(large.level, (1,) * large.dims))
            self.assertIsNone(store.get(self.key))
            self.assertIsNone(store.get(replace(self.key, content_hash='new1')))
            self.assertEqual(len(store), 2)
            self.assertEqual(store.size_bytes(), size + self.entry_size(large))

    def test_zero_cap_and_invalid_caps(self):
        import service.vector_store as module
        with self.capped_store(0) as store:
            with self.assertRaises(module.CapacityError):
                store.put(self.key, self.vector)
            self.assertEqual((len(store), store.size_bytes()), (0, 0))
        for cap in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                self.VectorStore(self.path, max_bytes=cap)

    def test_round_trip(self):
        with self.VectorStore(self.path) as store:
            store.put(self.key, self.vector)
            self.assertEqual(store.get(self.key), self.vector)

    def test_identical_put_is_noop(self):
        with self.VectorStore(self.path) as store:
            store.put(self.key, self.vector)
            before = store._env.info()['last_txnid']
            store.put(self.key, self.vector)
            self.assertEqual(store._env.info()['last_txnid'], before)
            self.assertEqual(store.get(self.key), self.vector)

    def test_conflicting_put_preserves_original_after_reopen(self):
        import service.vector_store as module
        with self.VectorStore(self.path) as store:
            store.put(self.key, self.vector)
            with self.assertRaises(Exception) as caught:
                store.put(self.key, LevelVector(self.key.level, (9, 8)))
            self.assertIs(type(caught.exception), module.AppendOnlyError)
        with self.VectorStore(self.path) as store:
            self.assertEqual(store.get(self.key), self.vector)

    def test_keys_streams_exact_disjoint_keyspaces(self):
        identities = [('model', 'v1'), ('model', 'v2'), ('model', 'v10'),
                      ('modelx', 'v1'), ('a|b', 'c'), ('a', 'b|c'),
                      ('a\x00b', 'c'), ('a', 'b\x00c'), ('', ''),
                      ('é', '版本'), ('["a",', '"b"]')]
        with self.VectorStore(self.path) as store:
            self.assertTrue(callable(getattr(store, 'keys', None)),
                            'keyspace iteration must be available')
            for model_id, version in identities:
                for suffix in ('hash', 'hash2'):
                    key = replace(self.key, model_id=model_id,
                                  model_version=version, content_hash=suffix)
                    store.put(key, self.vector)
            for model_id, version in identities:
                expected = {replace(self.key, model_id=model_id,
                                    model_version=version, content_hash=suffix)
                            for suffix in ('hash', 'hash2')}
                iterator = store.keys(model_id, version)
                self.assertIs(iter(iterator), iterator)
                self.assertEqual(set(iterator), expected)
                for key in expected:
                    self.assertEqual(store.get(key), self.vector)
            self.assertEqual(list(store.keys('missing', 'v1')), [])

    def test_missing_key(self):
        with self.VectorStore(self.path) as store:
            self.assertIsNone(store.get(self.key))

    def test_reopen_persists(self):
        with self.VectorStore(self.path) as store:
            store.put(self.key, self.vector)
        with self.VectorStore(self.path) as store:
            self.assertEqual(store.get(self.key), self.vector)

    def test_each_key_field_distinguishes_entries(self):
        variants = [replace(self.key, **change) for change in (
            {'model_id': 'other'}, {'model_version': 'v2'},
            {'level': Level.BLOCK}, {'content_hash': 'other'}, {'dims': 3})]
        keys = [self.key] + variants
        self.assertEqual(len({key.encode() for key in keys}), len(keys))
        with self.VectorStore(self.path) as store:
            for i, key in enumerate(keys):
                store.put(key, LevelVector(key.level, (float(i),) * key.dims))
            for i, key in enumerate(keys):
                self.assertEqual(store.get(key).values, (float(i),) * key.dims)

    def test_separator_encoding_is_injective(self):
        keys = [replace(self.key, model_id=a, model_version=b)
                for a, b in [('a|b', 'c'), ('a', 'b|c'),
                             ('a\x00b', 'c'), ('a', 'b\x00c'),
                             ('["a",', '"b"]'), ('é', '版本')]]
        self.assertEqual(len({key.encode() for key in keys}), len(keys))

    def test_key_is_frozen(self):
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            self.key.dims = 3

    def test_put_rejects_mismatched_dimensions_and_level(self):
        with self.VectorStore(self.path) as store:
            for vector in (LevelVector(Level.SENTENCE, (1,)),
                           LevelVector(Level.BLOCK, (1, 2))):
                with self.assertRaises(ValueError):
                    store.put(self.key, vector)
            self.assertIsNone(store.get(self.key))

    def test_get_rejects_stored_dimensions_and_level_mismatch(self):
        with self.VectorStore(self.path) as store:
            store.put(self.key, self.vector)
        with lmdb.open(self.path) as env:
            with env.begin(write=True) as txn:
                raw = txn.get(self.key.encode())
                for key in (replace(self.key, dims=3), replace(self.key, level=Level.BLOCK)):
                    txn.put(key.encode(), raw)
        with self.VectorStore(self.path) as store:
            for key in (replace(self.key, dims=3), replace(self.key, level=Level.BLOCK)):
                with self.assertRaises(ValueError):
                    store.get(key)

    def test_values_are_float64_little_endian(self):
        with self.VectorStore(self.path) as store:
            store.put(self.key, self.vector)
        with lmdb.open(self.path) as env:
            with env.begin() as txn:
                self.assertTrue(txn.get(self.key.encode()).endswith(struct.pack('<2d', 1.25, -2.5)))

    def test_close_is_idempotent(self):
        store = self.VectorStore(self.path, map_size=1024 * 1024)
        store.close()
        store.close()
        with self.VectorStore(self.path) as reopened:
            self.assertIsNone(reopened.get(self.key))


if __name__ == '__main__':
    unittest.main()

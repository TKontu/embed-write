import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments import bench_cache as bench
from service.chunk import chunk_blocks
from service.embedder import HashEmbedder
from service.segcache import SegmentationCache
from service.segment import segment_sentences
from service.vector_store import VectorStore


class BenchmarkTests(unittest.TestCase):
    def test_document_is_lazy_deterministic_and_near_target(self):
        document = bench.synthetic_document(words=500, seed=7)
        self.assertIs(iter(document), document)
        blocks = list(document)
        self.assertTrue(blocks)
        self.assertEqual(blocks, list(bench.synthetic_document(words=500, seed=7)))
        self.assertNotEqual(blocks, list(bench.synthetic_document(words=500, seed=8)))
        self.assertLessEqual(abs(sum(len(b.text.split()) for b in blocks) - 500), 16)
        self.assertEqual(len({b.node_id for b in blocks}), len(blocks))
        self.assertTrue(all(b.block_type == 'paragraph' for b in blocks))
        self.assertTrue(all(5 <= len(segment_sentences(b.text)) <= 12 for b in blocks[:-1]))

    def test_cold_populates_distinct_keys_and_warm_never_embeds(self):
        calls = []
        original = HashEmbedder.embed
        warm = False
        original_get = VectorStore.get

        def get(store, key):
            nonlocal warm
            value = original_get(store, key)
            if value is not None:
                warm = True
            return value

        def embed(backend, texts, level):
            self.assertFalse(warm, 'embedding after warm cache hit')
            self.assertLessEqual(len(texts), 7)
            calls.extend(texts)
            return original(backend, texts, level)

        chunks = list(chunk_blocks(bench.synthetic_document(words=500),
                                  SegmentationCache(segment_sentences, 64)))
        expected = {(c.level, hashlib.sha256(c.text.encode()).hexdigest()) for c in chunks}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(HashEmbedder, 'embed', embed), patch.object(VectorStore, 'get', get):
                result = bench.run_benchmark(Path(tmp) / 'store', words=500, batch_size=7)
            self.assertEqual(result['chunks'], len(chunks))
            self.assertEqual(result['warm_hits'], len(chunks))
            self.assertEqual(len(calls), len(expected))
            self.assertTrue(warm)
            with VectorStore(Path(tmp) / 'store') as store:
                self.assertEqual({(k.level, k.content_hash) for k in store.keys('hash-stub', '1')}, expected)
                self.assertEqual(len(store), len(expected))
                self.assertEqual(result['store_bytes'], store.size_bytes())
            with self.assertRaises(ValueError):
                bench.run_benchmark(Path(tmp) / 'store', words=500)
        self.assertEqual(result['words'], sum(len(b.text.split()) for b in bench.synthetic_document(words=500)))
        self.assertEqual(result['blocks'] + result['sentences'], result['chunks'])
        self.assertGreaterEqual(result['cold_seconds'], 0)
        self.assertGreaterEqual(result['warm_seconds'], 0)

    def test_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'result.json'
            subprocess.run([sys.executable, '-m', 'experiments.bench_cache', '--out', str(out), '--words', '500'], check=True)
            self.assertTrue(out.is_file(), 'CLI must write its JSON result')
            result = json.loads(out.read_text())
        self.assertEqual(set(result), {'words', 'blocks', 'sentences', 'chunks', 'cold_seconds', 'warm_seconds', 'warm_hits', 'store_bytes', 'embedder', 'python', 'platform'})
        self.assertEqual(result['warm_hits'], result['chunks'])

    def test_invalid_sizes_fail_before_store_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'store'
            for kwargs in ({'words': 0}, {'words': -1}, {'batch_size': 0}, {'batch_size': True}, {'dims': 0}):
                with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                    bench.run_benchmark(path, **kwargs)
                self.assertFalse(path.exists())

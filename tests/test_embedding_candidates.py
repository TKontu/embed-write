"""Synthetic checks for EM-02 candidates and OnnxEmbedder; LLM-built fakes, no model."""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from service.candidates import CANDIDATES, CandidateModel, OnnxEmbedder
from service.determinism import check_determinism
from service.normalize import l2_normalize
from service.embedder import EmbedderError, embed
from service.truncate import embed_truncated, supported_dims
from service.vectors import Level, LevelVector


def tiny(pooling='mean', max_tokens=4, dims=2, truncatable=(1, 2)):
    return CandidateModel('fake/model', 'rev1', dims, truncatable, max_tokens,
                          pooling, 'q: ', 'p: ')


class Encoding:
    def __init__(self, ids):
        self.ids = ids
        self.attention_mask = [1] * len(ids)


class FakeTokenizer:
    """Each character becomes one token whose id is its code point."""

    def __init__(self):
        self.seen = []

    def encode_batch(self, texts):
        self.seen.extend(texts)
        return [Encoding([ord(c) for c in text]) for text in texts]


class FakeSession:
    """Token hidden state: [id, 1]; padding gets a large value that masking must drop."""

    def __init__(self):
        self.feeds = []

    def run(self, output_names, feeds):
        self.feeds.append(feeds)
        hidden = [[[float(i), 1.0] if m else [1000.0, -1000.0]
                   for i, m in zip(ids, mask)]
                  for ids, mask in zip(feeds['input_ids'], feeds['attention_mask'])]
        return [hidden]


def unit(values):
    return tuple(l2_normalize(values))


def adapter(**kw):
    return OnnxEmbedder(tiny(**kw), '/nonexistent', session=FakeSession(),
                        tokenizer=FakeTokenizer())


class CandidateRegistryTests(unittest.TestCase):
    def test_registry_has_bge_m3_and_a_matryoshka_model(self):
        by_id = {c.model_id: c for c in CANDIDATES}
        bge = by_id['BAAI/bge-m3']
        self.assertEqual((bge.dims, bge.pooling, bge.max_tokens), (1024, 'cls', 8192))
        self.assertTrue(any(len(c.truncatable_dims) > 1 and c.pooling == 'mean'
                            for c in CANDIDATES))
        for c in CANDIDATES:
            self.assertIn(c.dims, c.truncatable_dims)

    def test_record_is_frozen_and_validated(self):
        c = tiny()
        with self.assertRaises(Exception):
            c.dims = 3
        with self.assertRaises(ValueError):
            tiny(pooling='max')
        with self.assertRaises(ValueError):
            tiny(truncatable=(1, 3))


class OnnxEmbedderTests(unittest.TestCase):
    def test_mean_pooling_masks_padding_and_normalizes(self):
        e = adapter()
        out = e.embed(['ab', 'abcdef'], Level.BLOCK)
        # 'p: ab' truncated to 4 tokens 'p: a'; padding never reaches the mean.
        first = [ord(c) for c in 'p: a']
        self.assertEqual(out[0].values, unit([sum(first) / 4, 1.0]))
        self.assertEqual(out[0].level, Level.BLOCK)
        self.assertAlmostEqual(sum(v * v for v in out[1].values), 1.0)

    def test_masking_with_short_input(self):
        e = OnnxEmbedder(tiny(max_tokens=10), 'x', session=FakeSession(),
                         tokenizer=FakeTokenizer())
        out = e.embed(['a', 'abcdef'], Level.BLOCK)
        ids = [ord(c) for c in 'p: a']
        self.assertEqual(out[0].values, unit([sum(ids) / 4, 1.0]))

    def test_cls_pooling_uses_first_token(self):
        e = adapter(pooling='cls')
        out = e.embed(['zz'], Level.SENTENCE)
        self.assertEqual(out[0].values, unit([float(ord('p')), 1.0]))

    def test_truncates_to_max_tokens_and_keeps_order(self):
        session = FakeSession()
        e = OnnxEmbedder(tiny(max_tokens=3), 'x', session=session,
                         tokenizer=FakeTokenizer())
        out = e.embed(['a', 'b', 'c'], Level.BLOCK)
        self.assertTrue(all(len(row) <= 3 for row in session.feeds[0]['input_ids']))
        self.assertEqual(len({v.values for v in out}), 1)  # 'p: ' prefix only, 3 tokens
        e2 = OnnxEmbedder(tiny(max_tokens=8), 'x', session=FakeSession(),
                          tokenizer=FakeTokenizer())
        a, b = e2.embed(['a', 'zzzz'], Level.BLOCK)
        b2, a2 = e2.embed(['zzzz', 'a'], Level.BLOCK)
        self.assertEqual((a, b), (a2, b2))

    def test_wrappers_accept_adapter(self):
        e = adapter()
        self.assertIsInstance(embed(e, ['x', 'y', 'z'], Level.BLOCK, batch_size=2)[0],
                              LevelVector)
        self.assertEqual(supported_dims(e), (1, 2))
        out = embed_truncated(e, ['x'], Level.BLOCK, 1)
        self.assertEqual(out[0].values, (1.0,))
        check_determinism(e, ['a', 'bb', 'ccc'], Level.BLOCK, batch_size=2)

    def test_empty_input(self):
        self.assertEqual(adapter().embed([], Level.BLOCK), [])

    def test_missing_files_raise_embedder_error(self):
        with tempfile.TemporaryDirectory() as d:
            e = OnnxEmbedder(tiny(), d)
            with mock.patch.dict(sys.modules, {'onnxruntime': mock.MagicMock(),
                                               'tokenizers': mock.MagicMock()}):
                with self.assertRaisesRegex(EmbedderError, 'model.onnx'):
                    e.embed(['x'], Level.BLOCK)
                open(os.path.join(d, 'model.onnx'), 'wb').close()
                with self.assertRaisesRegex(EmbedderError, 'tokenizer.json'):
                    e.embed(['x'], Level.BLOCK)

    def test_missing_package_raises_embedder_error(self):
        e = OnnxEmbedder(tiny(), '/nonexistent')
        with mock.patch.dict(sys.modules, {'onnxruntime': None}):
            with self.assertRaisesRegex(EmbedderError, 'onnxruntime'):
                e.embed(['x'], Level.BLOCK)
        with mock.patch.dict(sys.modules, {'onnxruntime': mock.MagicMock(),
                                           'tokenizers': None}):
            with self.assertRaisesRegex(EmbedderError, 'tokenizers'):
                e.embed(['x'], Level.BLOCK)

    def test_import_does_not_load_onnxruntime(self):
        code = ('import sys, service.candidates; '
                'sys.exit(int("onnxruntime" in sys.modules or "tokenizers" in sys.modules))')
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(subprocess.run([sys.executable, '-c', code], cwd=root).returncode, 0)


if __name__ == '__main__':
    unittest.main()

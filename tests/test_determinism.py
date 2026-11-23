import math
import unittest

from service.determinism import DeterminismError, check_determinism
from service.embedder import EmbedderError, HashEmbedder
from service.vectors import Level, LevelVector


class RecordingEmbedder:
    dims = 2

    def __init__(self):
        self.calls = []

    def embed(self, texts, level):
        self.calls.append(list(texts))
        return [LevelVector(level, (float(len(text)), 1)) for text in texts]


class CounterEmbedder(RecordingEmbedder):
    model_id = 'counter'
    model_version = 'test-1'

    def embed(self, texts, level):
        vectors = super().embed(texts, level)
        if len(self.calls) > 1:
            vectors[1] = LevelVector(level, (math.nextafter(vectors[1].values[0],
                                                         math.inf), 1))
        return vectors


class OrderEmbedder(RecordingEmbedder):
    def embed(self, texts, level):
        return [LevelVector(level, (index, 1)) for index, _ in enumerate(texts)]


class BatchEmbedder(RecordingEmbedder):
    def embed(self, texts, level):
        return [LevelVector(level, (len(texts), 1)) for _ in texts]


class DeterminismTests(unittest.TestCase):
    def test_hash_passes_all_levels_and_batch_sizes(self):
        for level in Level:
            for batch_size in (None, 1, 2, 64):
                with self.subTest(level=level, batch_size=batch_size):
                    self.assertIsNone(check_determinism(
                        HashEmbedder(), ['alpha', '', 'λ', 'alpha', 'omega'],
                        level, runs=4, batch_size=batch_size))

    def test_runs_reverse_and_singleton_batches_are_exercised(self):
        backend = RecordingEmbedder()
        texts = ['a', 'bb', 'ccc']
        check_determinism(backend, texts, Level.BLOCK, runs=2, batch_size=3)
        self.assertEqual(backend.calls, [texts, texts, texts[::-1],
                                         ['a'], ['bb'], ['ccc']])
        self.assertEqual(texts, ['a', 'bb', 'ccc'])

    def test_default_runs_and_no_extra_batch_comparison(self):
        backend = RecordingEmbedder()
        check_determinism(backend, ['a', 'bb'], Level.BLOCK)
        self.assertEqual(backend.calls, [['a', 'bb']] * 3 + [['bb', 'a']])

    def test_first_differing_index_run_and_identity(self):
        with self.assertRaises(DeterminismError) as caught:
            check_determinism(CounterEmbedder(), ['a', 'bb', 'ccc'], Level.BLOCK)
        message = str(caught.exception)
        for expected in ('input index 1', 'run 2', 'counter', 'test-1'):
            self.assertIn(expected, message)
        self.assertIsInstance(caught.exception, EmbedderError)
        self.assertNotIn('ccc', message)

    def test_order_dependence_without_identity_attributes(self):
        with self.assertRaisesRegex(DeterminismError, 'input index 0.*run 4.*reversed'):
            check_determinism(OrderEmbedder(), ['a', 'bb', 'ccc'], Level.BLOCK)

    def test_batch_dependence(self):
        with self.assertRaisesRegex(DeterminismError, 'input index 0.*run 5.*batch_size=1'):
            check_determinism(BatchEmbedder(), ['a', 'bb'], Level.BLOCK,
                              batch_size=2)

    def test_runs_below_two_rejected_before_embedding(self):
        backend = RecordingEmbedder()
        for runs in (-1, 0, 1):
            with self.subTest(runs=runs), self.assertRaises(ValueError):
                check_determinism(backend, ['a'], Level.BLOCK, runs=runs)
        self.assertEqual(backend.calls, [])

    def test_empty_input_passes_without_backend_calls(self):
        backend = RecordingEmbedder()
        self.assertIsNone(check_determinism(backend, [], Level.BLOCK, batch_size=2))
        self.assertEqual(backend.calls, [])


if __name__ == '__main__':
    unittest.main()

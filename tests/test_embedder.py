import math
import unittest

from service.embedder import EmbedderError, HashEmbedder, embed
from service.vectors import CrossLevelError, Level, LevelVector, cosine


class SpyEmbedder:
    model_id = 'spy'
    model_version = '1'
    dims = 2

    def __init__(self):
        self.calls = []

    def embed(self, texts, level):
        self.calls.append(list(texts))
        return [LevelVector(level, (float(text), 1)) for text in texts]


class EmbedderTests(unittest.TestCase):
    def test_levels_order_count_and_batches(self):
        for level in Level:
            with self.subTest(level=level):
                backend = SpyEmbedder()
                result = embed(backend, ('1', '2', '3', '4', '5'), level,
                               batch_size=2)
                self.assertEqual(backend.calls, [['1', '2'], ['3', '4'], ['5']])
                self.assertEqual([v.values[0] for v in result], [1, 2, 3, 4, 5])
                self.assertTrue(all(v.level is level for v in result))

    def test_default_batch_bound(self):
        backend = SpyEmbedder()
        result = embed(backend, ['1'] * 130, Level.SENTENCE)
        self.assertEqual([len(batch) for batch in backend.calls], [64, 64, 2])
        self.assertEqual(len(result), 130)

    def test_empty_does_not_call_backend(self):
        backend = SpyEmbedder()
        self.assertEqual(embed(backend, [], Level.BLOCK), [])
        self.assertEqual(backend.calls, [])

    def test_invalid_inputs_rejected_before_backend_call(self):
        backend = SpyEmbedder()
        for texts in ('text', b'text', None, {'1'}, iter(['1']), ['1', 2]):
            with self.subTest(texts=texts), self.assertRaises(TypeError):
                embed(backend, texts, Level.SENTENCE)
        with self.assertRaises(TypeError):
            embed(backend, [], 'sentence')
        # Even invalid text in a later batch must fail before model work.
        with self.assertRaises(TypeError):
            embed(backend, ['1', '2', None], Level.SENTENCE, batch_size=1)
        self.assertEqual(backend.calls, [])

    def test_invalid_batch_sizes(self):
        for size in (0, -1, 1.5, True, None):
            with self.subTest(size=size), self.assertRaises((TypeError, ValueError)):
                embed(SpyEmbedder(), ['1'], Level.SENTENCE, batch_size=size)

    def test_invalid_backend_outputs(self):
        cases = [None, (), [], [LevelVector(Level.SENTENCE, (1, 2))] * 2,
                 [LevelVector(Level.BLOCK, (1, 2))],
                 [LevelVector(Level.SENTENCE, (1,))], [(1, 2)]]
        for output in cases:
            with self.subTest(output=output):
                backend = SpyEmbedder()
                backend.embed = lambda texts, level: output
                with self.assertRaises(EmbedderError):
                    embed(backend, ['1'], Level.SENTENCE)
        self.assertTrue(issubclass(EmbedderError, RuntimeError))

    def test_later_batch_is_validated(self):
        backend = SpyEmbedder()
        original = backend.embed
        backend.embed = lambda texts, level: original(texts, level) if texts[0] == '1' else []
        with self.assertRaises(EmbedderError):
            embed(backend, ['1', '2'], Level.SENTENCE, batch_size=1)

    def test_invalid_dimensions(self):
        for dims in (0, -1, 1.5, True):
            with self.subTest(dims=dims):
                backend = SpyEmbedder()
                backend.dims = dims
                with self.assertRaises(EmbedderError):
                    embed(backend, ['1'], Level.SENTENCE)
                with self.assertRaises((TypeError, ValueError)):
                    HashEmbedder(dims=dims)

    def test_hash_deterministic_unit_norm_all_levels(self):
        for dims in (1, 7, 64):
            for level in Level:
                with self.subTest(dims=dims, level=level):
                    a = HashEmbedder(dims=dims)
                    b = HashEmbedder(dims=dims)
                    texts = ['alpha', '', 'Unicode: λ', 'alpha']
                    result = embed(a, texts, level, batch_size=1)
                    self.assertEqual(result, embed(b, texts, level, batch_size=3))
                    self.assertEqual(result[0], result[3])
                    for vector in result:
                        self.assertIs(vector.level, level)
                        self.assertEqual(len(vector.values), dims)
                        self.assertAlmostEqual(math.hypot(*vector.values), 1)
                        self.assertTrue(all(-1 <= x <= 1 for x in vector.values))

    def test_hash_depends_on_text_model_and_level(self):
        backend = HashEmbedder()
        first, second = embed(backend, ['a', 'b'], Level.SENTENCE)
        self.assertNotEqual(first.values, second.values)
        other_model = embed(HashEmbedder(model_id='other'), ['a'], Level.SENTENCE)[0]
        other_level = embed(backend, ['a'], Level.BLOCK)[0]
        self.assertNotEqual(first.values, other_model.values)
        self.assertNotEqual(first.values, other_level.values)

    def test_cosine_connection(self):
        backend = HashEmbedder()
        a, b = embed(backend, ['same', 'same'], Level.SENTENCE)
        self.assertAlmostEqual(cosine(a, b), 1)
        c = embed(backend, ['same'], Level.BLOCK)[0]
        with self.assertRaises(CrossLevelError):
            cosine(a, c)


if __name__ == '__main__':
    unittest.main()

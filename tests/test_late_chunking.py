"""Synthetic, LLM-built checks; no model or quality claims."""
import importlib.util
import math
import unittest


class LateChunkingTests(unittest.TestCase):
    def test_arm_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.arms.late_chunking'))

    def test_normalized_mean_order_level_and_single_call(self):
        from experiments.arms.late_chunking import late_chunk
        from service.vectors import Level
        backend = Fixed([[2, 0], [0, 2], [0, 3]], [(0, 2), (2, 4), (4, 6)])
        result = late_chunk('abcdef', [(0, 4), (4, 6)], backend, Level.SENTENCE)
        self.assertEqual(len(result), 2)
        self.assertEqual(backend.calls, ['abcdef'])
        self.assertEqual(result[0].level, Level.SENTENCE)
        for value in result[0].values:
            self.assertAlmostEqual(value, 1 / math.sqrt(2))
        self.assertEqual(result[1].values, (0, 1))

    def test_straddling_token_counts_for_both(self):
        from experiments.arms.late_chunking import late_chunk
        from service.vectors import Level
        result = late_chunk('abcdef', [(0, 3), (3, 6)],
                            Fixed([[1, 0], [0, 1]], [(0, 4), (4, 6)]), Level.BLOCK)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].values, (1, 0))
        self.assertAlmostEqual(result[1].values[0], 1 / math.sqrt(2))
        self.assertTrue(all(v.level is Level.BLOCK for v in result))

    def test_invalid_sentence_spans(self):
        from experiments.arms.late_chunking import late_chunk, LateChunkingError
        from service.vectors import Level
        for spans in [[(-1, 2)], [(0, 7)], [(2, 2)], [(3, 2)],
                      [(0, 4), (3, 6)], [(4, 6), (0, 2)], [(0.5, 2)], [(True, 2)]]:
            with self.subTest(spans=spans), self.assertRaises(LateChunkingError):
                late_chunk('abcdef', spans, Fixed([[1]], [(0, 6)]), Level.SENTENCE)

    def test_invalid_token_spans(self):
        from experiments.arms.late_chunking import late_chunk, LateChunkingError
        from service.vectors import Level
        for spans in [[(-1, 2)], [(0, 7)], [(2, 2)], [(3, 2)],
                      [(0, 4), (3, 6)], [(4, 6), (0, 2)]]:
            with self.subTest(spans=spans), self.assertRaises(LateChunkingError):
                late_chunk('abcdef', [(0, 6)], Fixed([[1]] * len(spans), spans), Level.SENTENCE)

    def test_no_overlapping_token_including_touching_boundary(self):
        from experiments.arms.late_chunking import late_chunk, LateChunkingError
        from service.vectors import Level
        for vectors, spans in [([], []), ([[1]], [(3, 6)])]:
            with self.subTest(spans=spans), self.assertRaises(LateChunkingError):
                late_chunk('abcdef', [(0, 3)], Fixed(vectors, spans), Level.SENTENCE)

    def test_bad_vectors(self):
        from experiments.arms.late_chunking import late_chunk, LateChunkingError
        from service.vectors import Level
        for vectors in [[[1], [1, 2]], [[], []], [[math.nan], [1]],
                        [[1], [math.inf]], [[-math.inf], [1]], [[0], [0]], [[1], [-1]]]:
            with self.subTest(vectors=vectors), self.assertRaises(LateChunkingError):
                late_chunk('ab', [(0, 2)], Fixed(vectors, [(0, 1), (1, 2)]), Level.SENTENCE)

    def test_token_count_mismatch(self):
        from experiments.arms.late_chunking import late_chunk, LateChunkingError
        from service.vectors import Level
        with self.assertRaises(LateChunkingError):
            late_chunk('ab', [(0, 2)], Fixed([[1]], []), Level.SENTENCE)

    def test_empty_sentences(self):
        from experiments.arms.late_chunking import late_chunk
        from service.vectors import Level
        self.assertEqual(late_chunk('', [], Fixed([], []), Level.SENTENCE), [])


class Fixed:
    """Deterministic stdlib token-embedding double for tests only; not a model."""
    def __init__(self, vectors, spans):
        self.vectors, self.spans, self.calls = vectors, spans, []

    def embed_tokens(self, text):
        self.calls.append(text)
        return self.vectors, self.spans

"""Offline contract checks for optional prefix truncation."""

import math
import unittest

from service import truncate as api
from service.embedder import EmbedderError, HashEmbedder
from service.normalize import NormalizationError
from service.vectors import Level, LevelVector


class Backend:
    model_id = 'fake'
    model_version = '1'
    dims = 8
    truncatable_dims = (8, 4)

    def __init__(self):
        self.calls = []
        self.vector = LevelVector(Level.BLOCK, (3, 4, 0, 0, 1, 2, 3, 4))

    def embed(self, texts, level):
        self.calls.append(list(texts))
        return [self.vector for _ in texts]


class TruncateTests(unittest.TestCase):
    def test_prefix_is_normalized_and_level_preserved(self):
        for level in Level:
            vector = LevelVector(level, (3, 4, 12))
            result = api.truncate(vector, 2)
            self.assertEqual(result.values, (0.6, 0.8))
            self.assertAlmostEqual(math.hypot(*result.values), 1)
            self.assertIs(result.level, level)
            self.assertEqual(vector.values, (3, 4, 12))

    def test_full_dimension_is_identity(self):
        vector = LevelVector(Level.SENTENCE, (3, 4))
        self.assertIs(api.truncate(vector, 2), vector)
        backend = Backend()
        result = api.embed_truncated(backend, ['x'], Level.BLOCK, 8)
        self.assertIs(result[0], backend.vector)

    def test_invalid_dimensions(self):
        vector = LevelVector(Level.BLOCK, (3, 4))
        for dims in (-1, 0, 3):
            with self.subTest(dims=dims), self.assertRaises(ValueError):
                api.truncate(vector, dims)
        for dims in (True, 1.5, '1'):
            with self.subTest(dims=dims), self.assertRaises(TypeError):
                api.truncate(vector, dims)

    def test_zero_prefix_is_an_error(self):
        vector = LevelVector(Level.BLOCK, (0, 0, 1))
        with self.assertRaises(NormalizationError):
            api.truncate(vector, 2)
        backend = Backend()
        backend.vector = LevelVector(Level.BLOCK, (0, 0, 0, 0, 1, 0, 0, 0))
        with self.assertRaises(NormalizationError):
            api.embed_truncated(backend, ['x'], Level.BLOCK, 4)

    def test_declared_dimensions_sorted_and_batched(self):
        backend = Backend()
        self.assertEqual(api.supported_dims(backend), (4, 8))
        result = api.embed_truncated(backend, ['a', 'b', 'c'], Level.BLOCK,
                                     4, batch_size=2)
        self.assertEqual(backend.calls, [['a', 'b'], ['c']])
        self.assertEqual(len(result), 3)
        for vector in result:
            self.assertEqual(vector.values, (0.6, 0.8, 0, 0))
            self.assertIs(vector.level, Level.BLOCK)

    def test_unsupported_dimension_rejected_before_backend(self):
        backend = Backend()
        self.assertTrue(issubclass(api.TruncationError, EmbedderError))
        for dims in (0, 2, 9):
            with self.subTest(dims=dims), self.assertRaises(api.TruncationError):
                api.embed_truncated(backend, ['a'], Level.BLOCK, dims)
        self.assertEqual(backend.calls, [])

    def test_backend_without_declaration_only_allows_full_dimension(self):
        backend = HashEmbedder(dims=8)
        self.assertEqual(api.supported_dims(backend), (8,))
        with self.assertRaises(api.TruncationError):
            api.embed_truncated(backend, ['a'], Level.BLOCK, 4)
        result = api.embed_truncated(backend, ['a'], Level.BLOCK, 8)
        self.assertEqual(result, backend.embed(['a'], Level.BLOCK))

    def test_invalid_backend_declaration_rejected(self):
        for declaration in ((0, 8), (9,), (4.0,), (True,), None):
            backend = Backend()
            backend.truncatable_dims = declaration
            with self.subTest(declaration=declaration), self.assertRaises(EmbedderError):
                api.supported_dims(backend)

    def test_wrapper_keeps_embedding_validation(self):
        backend = Backend()
        with self.assertRaises(EmbedderError):
            api.embed_truncated(backend, ['a'], Level.SENTENCE, 4)
        with self.assertRaises(ValueError):
            api.embed_truncated(backend, ['a'], Level.BLOCK, 4, batch_size=0)
        self.assertEqual(api.embed_truncated(backend, [], Level.BLOCK, 4), [])

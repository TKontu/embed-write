import dataclasses
import importlib
import math
import unittest


class VectorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('service.vectors'),
                             'level-tagged vector API is missing')
        self.v = importlib.import_module('service.vectors')

    def vec(self, values=(3, 4), level=None):
        return self.v.LevelVector(level or self.v.Level.SENTENCE, values)

    def test_same_level_scores_and_equality(self):
        a, b = self.vec(), self.vec((4, 3))
        self.assertEqual(self.v.dot(a, b), 24)
        self.assertAlmostEqual(self.v.cosine(a, b), .96)
        self.assertEqual(a, self.vec())
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, (3, 4))

    def test_cross_level_operations_raise(self):
        for level in (self.v.Level.BLOCK, self.v.Level.SECTION):
            a, b = self.vec(), self.vec(level=level)
            for op in (self.v.dot, self.v.cosine, lambda a, b: a == b,
                       lambda a, b: a != b):
                with self.subTest(level=level, op=op):
                    with self.assertRaises(self.v.CrossLevelError):
                        op(a, b)
        self.assertTrue(issubclass(self.v.CrossLevelError, TypeError))

    def test_dimensions_rejected(self):
        for op in (self.v.dot, self.v.cosine):
            with self.assertRaises(ValueError):
                op(self.vec(), self.vec((1,)))

    def test_invalid_values_rejected(self):
        for values in ((), (math.nan,), (math.inf,), (-math.inf,)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.vec(values)
        with self.assertRaises(TypeError):
            self.vec(level='SENTENCE')

    def test_normalized_preserves_level(self):
        for level in self.v.Level:
            result = self.v.normalized(self.vec(level=level))
            self.assertIs(result.level, level)
            self.assertAlmostEqual(sum(x*x for x in result.values), 1)

    def test_immutable_float_tuple(self):
        source = [3, 4]
        a = self.vec(source)
        source[0] = 99
        self.assertEqual(a.values, (3., 4.))
        self.assertTrue(all(isinstance(x, float) for x in a.values))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.level = self.v.Level.BLOCK
        with self.assertRaises(TypeError):
            a.values[0] = 1

    def test_zero_and_extreme_cosine(self):
        with self.assertRaises(ValueError):
            self.v.cosine(self.vec((0, 0)), self.vec())
        self.assertAlmostEqual(self.v.cosine(self.vec((1e308, 1e308)),
                                            self.vec((1e308, 1e308))), 1)

"""NM-01: stable default normalization and lazy batch processing."""

import math
import sys
import types
import unittest

from service.normalize import NormalizationError, l2_normalize, l2_normalize_batch


class NormalizeTests(unittest.TestCase):
    def assertUnit(self, vector):
        self.assertTrue(all(math.isfinite(value) for value in vector))
        self.assertAlmostEqual(math.hypot(*vector), 1.0, delta=1e-12)

    def test_unit_norm(self):
        result = l2_normalize([3.0, 4.0])
        self.assertIsInstance(result, list)
        self.assertEqual(result, [0.6, 0.8])
        self.assertUnit(result)

    def test_direction_preserved(self):
        vector = [-3.0, 0.0, 4.0, -12.0]
        result = l2_normalize(vector)
        cosine = math.fsum(a * b for a, b in zip(vector, result)) / math.hypot(*vector)
        self.assertAlmostEqual(cosine, 1.0, delta=1e-12)

    def test_zero_rejected(self):
        self.assertTrue(issubclass(NormalizationError, ValueError))
        with self.assertRaises(NormalizationError):
            l2_normalize([0.0, -0.0])

    def test_nonfinite_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            for vector in ([value, 1.0], [1.0, value]):
                with self.subTest(vector=vector), self.assertRaises(NormalizationError):
                    l2_normalize(vector)

    def test_empty_rejected(self):
        with self.assertRaises(NormalizationError):
            l2_normalize([])

    def test_already_unit(self):
        vector = (0.6, -0.8, 0.0)
        result = l2_normalize(vector)
        self.assertUnit(result)
        for actual, expected in zip(result, vector):
            self.assertAlmostEqual(actual, expected, delta=1e-12)

    def test_idempotent(self):
        once = l2_normalize([2.0, -7.0, 9.0])
        twice = l2_normalize(once)
        for actual, expected in zip(twice, once):
            self.assertAlmostEqual(actual, expected, delta=1e-12)

    def test_extreme_magnitudes(self):
        for magnitude in (sys.float_info.max, 1e308, 1e-300, math.ulp(0.0)):
            with self.subTest(magnitude=magnitude):
                result = l2_normalize([magnitude, -magnitude])
                self.assertUnit(result)
                self.assertAlmostEqual(result[0], math.sqrt(0.5), delta=1e-12)
                self.assertEqual(result[1], -result[0])

    def test_mixed_magnitudes(self):
        result = l2_normalize([sys.float_info.max, math.ulp(0.0), -1.0])
        self.assertUnit(result)
        self.assertEqual(result[0], 1.0)
        self.assertLess(result[2], 0.0)

    def test_input_unchanged(self):
        vector = [3.0, 4.0]
        self.assertIsNot(l2_normalize(vector), vector)
        self.assertEqual(vector, [3.0, 4.0])

    def test_batch_streams_lazily(self):
        consumed = []

        def source():
            for i in range(3):
                consumed.append(i)
                yield [3.0, 4.0]

        batch = l2_normalize_batch(source())
        self.assertIsInstance(batch, types.GeneratorType)
        self.assertEqual(consumed, [])
        self.assertEqual(next(batch), [0.6, 0.8])
        self.assertEqual(consumed, [0])
        self.assertEqual(list(batch), [[0.6, 0.8], [0.6, 0.8]])
        self.assertEqual(consumed, [0, 1, 2])

    def test_batch_invalid_vector_fails_when_consumed(self):
        batch = l2_normalize_batch([[1.0], [0.0]])
        self.assertEqual(next(batch), [1.0])
        with self.assertRaises(NormalizationError):
            next(batch)

    def test_empty_batch(self):
        self.assertEqual(list(l2_normalize_batch(iter(()))), [])


if __name__ == "__main__":
    unittest.main()

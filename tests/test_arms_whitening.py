"""NM-02 arms on synthetic LLM-built vectors only."""

import json
import math
import random
import unittest

from experiments.arms.whitening import (
    Transform, WhiteningError, fit_abtt, fit_whitening)
from service.vectors import Level, LevelVector


def synthetic(n=400, d=4, seed=7):
    rng = random.Random(seed)
    mix = [[rng.uniform(-2, 2) for _ in range(d)] for _ in range(d)]
    out = []
    for _ in range(n):
        z = [rng.gauss(0, 1) for _ in range(d)]
        out.append([3.0 + j + sum(mix[j][k] * z[k] for k in range(d)) for j in range(d)])
    return out


def covariance(rows):
    n, d = len(rows), len(rows[0])
    mean = [sum(r[j] for r in rows) / n for j in range(d)]
    cov = [[sum((r[i] - mean[i]) * (r[j] - mean[j]) for r in rows) / (n - 1)
            for j in range(d)] for i in range(d)]
    return mean, cov


class WhiteningTests(unittest.TestCase):
    def test_whitened_fit_data_has_identity_covariance(self):
        data = synthetic()
        t = fit_whitening(data, Level.SENTENCE)
        mean, cov = covariance(list(t.apply_batch(data)))
        for i in range(4):
            self.assertAlmostEqual(mean[i], 0.0, places=9)
            for j in range(4):
                self.assertAlmostEqual(cov[i][j], 1.0 if i == j else 0.0, places=4)

    def test_zca_matrix_is_symmetric(self):
        t = fit_whitening(synthetic(), Level.SENTENCE)
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(t.matrix[i][j], t.matrix[j][i], places=10)

    def test_streaming_generator_equals_list_fit(self):
        data = synthetic()
        for fit in (fit_whitening, fit_abtt):
            a = fit(data, Level.BLOCK)
            b = fit((list(v) for v in data), Level.BLOCK)
            self.assertEqual(a, b)

    def test_dict_round_trip_gives_identical_vectors(self):
        data = synthetic()
        for fit in (fit_whitening, fit_abtt):
            t = fit(data, Level.SECTION)
            back = Transform.from_dict(json.loads(json.dumps(t.to_dict())))
            self.assertEqual(back, t)
            for v in data[:20]:
                self.assertEqual(back.apply(v), t.apply(v))

    def test_apply_batch_is_lazy(self):
        t = fit_whitening(synthetic(), Level.SENTENCE)
        it = t.apply_batch(iter([[1, 2, 3, 4], [1.0]]))
        self.assertEqual(len(next(it)), 4)
        with self.assertRaises(WhiteningError):
            next(it)

    def test_per_level_transforms_are_independent(self):
        s = fit_whitening(synthetic(seed=1), Level.SENTENCE)
        b = fit_whitening(synthetic(seed=2), Level.BLOCK)
        self.assertNotEqual(s.mean, b.mean)
        self.assertEqual(s, fit_whitening(synthetic(seed=1), Level.SENTENCE))
        with self.assertRaises(WhiteningError):
            s.apply(LevelVector(Level.BLOCK, (1.0, 2.0, 3.0, 4.0)))
        self.assertEqual(len(s.apply(LevelVector(Level.SENTENCE, (1.0, 2.0, 3.0, 4.0)))), 4)
        with self.assertRaises(WhiteningError):
            fit_whitening([LevelVector(Level.BLOCK, (1.0, 2.0))] * 3, Level.SENTENCE)


class AbttTests(unittest.TestCase):
    def test_output_orthogonal_to_removed_directions_and_zero_mean(self):
        data = synthetic(d=5)
        t = fit_abtt(data, Level.SENTENCE, n_components=2)
        self.assertEqual(len(t.components), 2)
        out = list(t.apply_batch(data))
        for v in out:
            for u in t.components:
                self.assertAlmostEqual(sum(a * b for a, b in zip(u, v)), 0.0, places=9)
        mean, _ = covariance(out)
        for m in mean:
            self.assertAlmostEqual(m, 0.0, places=9)

    def test_components_are_unit_and_top_variance(self):
        data = synthetic(d=5)
        t = fit_abtt(data, Level.SENTENCE, n_components=1)
        u = t.components[0]
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in u)), 1.0, places=10)
        _, cov = covariance(data)
        var_u = sum(u[i] * cov[i][j] * u[j] for i in range(5) for j in range(5))
        rng = random.Random(3)
        for _ in range(50):
            w = [rng.gauss(0, 1) for _ in range(5)]
            norm = math.sqrt(sum(x * x for x in w))
            w = [x / norm for x in w]
            var_w = sum(w[i] * cov[i][j] * w[j] for i in range(5) for j in range(5))
            self.assertGreaterEqual(var_u + 1e-9, var_w)


class ErrorTests(unittest.TestCase):
    def test_errors(self):
        for fit in (fit_whitening, fit_abtt):
            with self.assertRaisesRegex(WhiteningError, 'empty input'):
                fit([], Level.SENTENCE)
            with self.assertRaisesRegex(WhiteningError, 'at least 2'):
                fit([[1.0, 2.0, 3.0]], Level.SENTENCE)
            with self.assertRaisesRegex(WhiteningError, 'mismatched'):
                fit([[1.0, 2.0], [1.0, 2.0, 3.0]], Level.SENTENCE)
            with self.assertRaisesRegex(WhiteningError, 'finite'):
                fit([[1.0, 2.0], [math.nan, 2.0]], Level.SENTENCE)
            with self.assertRaisesRegex(WhiteningError, 'finite'):
                fit([[1.0, math.inf], [1.0, 2.0]], Level.SENTENCE)
            with self.assertRaisesRegex(WhiteningError, 'non-empty'):
                fit([[], []], Level.SENTENCE)
            with self.assertRaises(TypeError):
                fit(synthetic(), 'sentence')
        with self.assertRaisesRegex(WhiteningError, 'n_components'):
            fit_abtt(synthetic(d=3), Level.SENTENCE, n_components=3)
        t = fit_whitening(synthetic(), Level.SENTENCE)
        with self.assertRaisesRegex(WhiteningError, 'mismatched'):
            t.apply([1.0, 2.0])
        bad = t.to_dict()
        bad['n_fitted'] = 1
        with self.assertRaisesRegex(WhiteningError, 'n_fitted'):
            Transform.from_dict(bad)



class HardeningTests(unittest.TestCase):
    def test_jacobi_raises_when_sweeps_exhausted(self):
        from experiments.arms.whitening import _jacobi
        a = [[4.0, 1.0, 2.0], [1.0, 3.0, 0.5], [2.0, 0.5, 1.0]]
        with self.assertRaises(WhiteningError):
            _jacobi(a, max_sweeps=1)
        values, _ = _jacobi(a)
        self.assertEqual(len(values), 3)

    def test_covariance_overflow_raises(self):
        data = [[1e300, 0.0], [-1e300, 1.0], [1e300, 2.0]]
        with self.assertRaises(WhiteningError):
            fit_whitening(data, Level.SENTENCE)
        with self.assertRaises(WhiteningError):
            fit_abtt(data, Level.SENTENCE, n_components=1)

    def test_collinear_input_is_eps_regularized(self):
        rng = random.Random(3)
        data = []
        for _ in range(50):
            a, b = rng.gauss(0, 1), rng.gauss(0, 1)
            data.append([a, b, a + b])  # rank 2 in 3 dims
        t = fit_whitening(data, Level.SENTENCE)
        self.assertTrue(all(math.isfinite(x) for row in t.matrix for x in row))
        self.assertTrue(all(math.isfinite(x) for x in t.apply(data[0])))

    def test_collinear_input_without_eps_raises(self):
        data = [[float(i), 2.0 * i, -float(i)] for i in range(10)]
        with self.assertRaisesRegex(WhiteningError, 'degenerate'):
            fit_whitening(data, Level.SENTENCE, eps=0.0)

    def test_abtt_rejects_bool_n_components(self):
        data = synthetic(n=20)
        for flag in (True, False):
            with self.assertRaises(WhiteningError):
                fit_abtt(data, Level.SENTENCE, n_components=flag)


if __name__ == '__main__':
    unittest.main()

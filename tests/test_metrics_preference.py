"""Hand-computed, synthetic cases for MT-04 and MT-07 (LLM-built)."""

import importlib
from pathlib import Path
import random
import unittest


class PreferenceTests(unittest.TestCase):
    def metric(self):
        path = Path(__file__).resolve().parents[1] / 'experiments/metrics/preference.py'
        self.assertTrue(path.exists(), 'Preference metric is not implemented')
        return importlib.import_module('experiments.metrics.preference')

    def test_half_credit_for_ties(self):
        # (2 wins + 0.5 * 1 tie) / 4 pairs = 0.625.
        self.assertEqual(self.metric().win_rate(['a', 'b', 'a', 'tie']),
                         dict(win_rate=0.625, n=4, wins=2, losses=1, ties=1))

    def test_rejects_empty_and_unknown_choices(self):
        for choices in ([], ['a', 'unknown'], ['A'], [None]):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                self.metric().win_rate(choices)

    def test_bootstrap_constant_samples(self):
        # Every resample has the same score: 1, 0, or 1/2 respectively.
        metric = self.metric()
        self.assertTrue(hasattr(metric, 'bootstrap_interval'))
        for choice, score in (('a', 1.0), ('b', 0.0), ('tie', 0.5)):
            self.assertEqual(metric.bootstrap_interval([choice] * 3), (score, score))

    def test_seeded_percentiles_and_global_rng_isolation(self):
        metric = self.metric()
        self.assertTrue(hasattr(metric, 'bootstrap_interval'))
        state = random.getstate()
        # Random(0).randrange(2), grouped in pairs, gives 11,01,11,11.
        # For [a,b], sorted rates are [0,0,0,1/2]. With confidence 1/2,
        # ranks are .75 and 2.25; linear interpolation gives 0 and 1/8.
        result = metric.bootstrap_interval(['a', 'b'], 4, 0.5, 0)
        self.assertEqual(result, (0.0, 0.125))
        self.assertEqual(result, metric.bootstrap_interval(['a', 'b'], 4, 0.5, 0))
        self.assertEqual(random.getstate(), state)

    def test_mixed_interval_contains_estimate(self):
        metric = self.metric()
        self.assertTrue(hasattr(metric, 'bootstrap_interval'))
        choices = ['a', 'a', 'b', 'tie']
        lo, hi = metric.bootstrap_interval(choices)
        self.assertLessEqual(lo, 0.625)  # (2 + 1/2) / 4
        self.assertGreaterEqual(hi, 0.625)
        self.assertGreaterEqual(lo, 0)
        self.assertLessEqual(hi, 1)

    def test_bootstrap_rejects_invalid_inputs(self):
        metric = self.metric()
        self.assertTrue(hasattr(metric, 'bootstrap_interval'))
        for choices in ([], ['invalid']):
            with self.assertRaises(ValueError):
                metric.bootstrap_interval(choices)
        for count in (0, -1):
            with self.assertRaises(ValueError):
                metric.bootstrap_interval(['a'], n_resamples=count)
        for confidence in (0, 1, -0.1, 1.1, float('nan')):
            with self.assertRaises(ValueError):
                metric.bootstrap_interval(['a'], confidence=confidence)

    def test_single_resample(self):
        metric = self.metric()
        self.assertTrue(hasattr(metric, 'bootstrap_interval'))
        # A single tie always gives 1/2, including at both percentile ranks.
        self.assertEqual(metric.bootstrap_interval(('tie',), 1), (0.5, 0.5))

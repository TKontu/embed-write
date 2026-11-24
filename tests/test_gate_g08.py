"""Synthetic LLM-built rewrite pairs only; no corpus or expert data."""
import random
import tempfile
import unittest

from experiments.gates import g08
from experiments.metrics.meaning import RewritePair
from experiments.preregistration import PreregistrationError
from experiments.runner import run_gate, serialize


def pairs(prefix, n):
    out = []
    for i in range(n):
        out.append(RewritePair(f'{prefix}{i}k', f'The pump draws {i + 2} kW.',
                               f'The pump uses {i + 2} kW.', True))
        out.append(RewritePair(f'{prefix}{i}c', f'The pump draws {i + 2} kW.',
                               f'The pump uses {i + 3} kW.', False))
    return out


EVAL, CAL = pairs('e', 6), pairs('c', 5)
CONFIG = {'pairs': EVAL, 'calibration_pairs': CAL, 'n_resamples': 200}


class G08Tests(unittest.TestCase):
    def test_metric_rows(self):
        out = g08.run(random.Random(1), CONFIG)
        rows = {r['metric']: r for r in out['metrics']}
        self.assertEqual(set(rows), {'tpr', 'tnr', 'balanced_accuracy', 'flagged_precision'})
        for r in rows.values():
            self.assertIn('n', r)
            self.assertIn('method', r)
            lo, hi = r['interval']
            self.assertLessEqual(lo, hi)
        self.assertEqual(out['filter'], 'enabled')
        self.assertEqual(out['calibration']['threshold'], out['threshold'])
        self.assertEqual(rows['balanced_accuracy']['value'], 1.0)
        self.assertEqual(rows['flagged_precision']['n'], 6)

    def test_deterministic(self):
        a = g08.run(random.Random(3), CONFIG)
        self.assertEqual(serialize(a), serialize(g08.run(random.Random(3), CONFIG)))

    def test_loader_hook(self):
        out = g08.run(random.Random(0), {'loader': lambda: iter(EVAL), 'calibration_pairs': CAL,
                                         'n_resamples': 20})
        self.assertEqual(out['n_eval'], len(EVAL))

    def test_overlap_raises(self):
        with self.assertRaisesRegex(ValueError, 'both'):
            g08.run(random.Random(0), {'pairs': EVAL, 'calibration_pairs': CAL + EVAL[:1]})

    def test_missing_or_bad_splits(self):
        with self.assertRaisesRegex(ValueError, 'calibration_pairs'):
            g08.run(random.Random(0), {'pairs': EVAL})
        with self.assertRaisesRegex(ValueError, 'non-empty'):
            g08.run(random.Random(0), {'pairs': EVAL, 'calibration_pairs': []})
        with self.assertRaisesRegex(ValueError, 'non-empty'):
            g08.run(random.Random(0), {'pairs': [], 'calibration_pairs': CAL})
        with self.assertRaisesRegex(ValueError, 'RewritePair'):
            g08.run(random.Random(0), {'pairs': EVAL, 'calibration_pairs': ['x']})

    def test_disabled_filter_when_calibration_unreachable(self):
        # An arm that scores everything 0.0 flags every pair: precision 0.5 < 0.95.
        out = g08.run(random.Random(0), dict(CONFIG, arm=lambda o, c: 0.0))
        self.assertEqual(out['filter'], 'disabled')
        self.assertIsNone(out['calibration']['threshold'])
        self.assertEqual(out['threshold'], 0.5)
        rows = {r['metric']: r for r in out['metrics']}
        self.assertEqual(rows['tpr']['value'], 0.0)
        self.assertEqual(rows['tnr']['value'], 1.0)

    def test_run_gate_refuses_without_preregistration(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(PreregistrationError):
            run_gate(g08.run, seed=0, config=CONFIG, preregistration_root=root)
        with self.assertRaises(PreregistrationError):
            run_gate(g08.run, seed=0, config=CONFIG)


if __name__ == '__main__':
    unittest.main()

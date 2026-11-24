import tempfile
import unittest

from analysis.perturb import KINDS
from analysis.transitions import LabelledSection
from experiments.gates import g05
from experiments.preregistration import PreregistrationError
from experiments.runner import run_gate, serialize
import random


def sec(moves, doc, stype='intro'):
    return LabelledSection(doc, stype, tuple(moves))


SECTIONS = [sec('abcd', f'd{i}') for i in range(10)] + [sec('abd', 'd10')]
CONFIG = {'sections': SECTIONS, 'foreign_moves': ['z'], 'n_resamples': 200}


class G05Tests(unittest.TestCase):
    def test_deterministic(self):
        a = g05.run(random.Random(3), CONFIG)
        b = g05.run(random.Random(3), CONFIG)
        self.assertEqual(serialize(a), serialize(b))
        self.assertNotEqual(a['perturb_seed'], g05.run(random.Random(4), CONFIG)['perturb_seed'])

    def test_log_has_ground_truth(self):
        out = g05.run(random.Random(1), CONFIG)
        log = out['perturbation_log']
        self.assertEqual(len(log), out['score']['perturbations'])
        self.assertEqual(len(log), len(SECTIONS) * len(KINDS))
        for rec in log:
            self.assertIn(rec['kind'], KINDS)
            self.assertNotEqual(rec['original'], rec['perturbed'])
            self.assertTrue(rec['positions'])
            self.assertTrue(rec['document_id'])

    def test_metric_rows_and_false_flags(self):
        out = g05.run(random.Random(1), CONFIG)
        rows = {r['metric']: r for r in out['metrics']}
        self.assertEqual(set(rows), {'precision', 'recall', 'false_flags_per_unperturbed_report'})
        for r in rows.values():
            self.assertIn('n', r)
            lo, hi = r['interval']
            self.assertLessEqual(lo, hi)
        ff = rows['false_flags_per_unperturbed_report']
        self.assertEqual(ff['n'], len(SECTIONS))
        self.assertEqual(ff['count'], out['score']['false_flags_unperturbed'])
        self.assertGreater(ff['count'], 0)  # 'abd' misses expected move 'c'
        self.assertEqual(rows['recall']['n'], len(out['perturbation_log']))

    def test_loader_hook(self):
        out = g05.run(random.Random(1), {'loader': lambda: iter(SECTIONS), 'foreign_moves': ['z'],
                                         'n_resamples': 50})
        self.assertEqual(out['metrics'][2]['n'], len(SECTIONS))

    def test_empty_sections(self):
        with self.assertRaisesRegex(ValueError, 'non-empty sections'):
            g05.run(random.Random(0), {'sections': []})
        with self.assertRaisesRegex(ValueError, 'loader'):
            g05.run(random.Random(0), {})

    def test_run_gate_refuses_without_preregistration(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(PreregistrationError):
            run_gate(g05.run, seed=0, config=CONFIG, preregistration_root=root)
        with self.assertRaises(PreregistrationError):
            run_gate(g05.run, seed=0, config=CONFIG)


if __name__ == '__main__':
    unittest.main()

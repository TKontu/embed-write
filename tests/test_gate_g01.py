"""Synthetic LLM-built label fixtures only; no corpus, store or expert data."""
import random
import tempfile
import unittest

from experiments.gates import g01
from experiments.preregistration import PreregistrationError
from experiments.runner import run_gate, serialize
from experiments.splits import DocumentSplit, SplitLeakError

LABELS = ['claim', 'evidence', 'other']
# Synthetic fixture: 10 sentences. Hand-computed expert-vs-LLM kappa:
# matrix rows expert, cols llm (claim, evidence, other):
#   claim    [3, 1, 0]   row 4
#   evidence [0, 3, 1]   row 4
#   other    [0, 0, 2]   row 2
# cols 3, 4, 3; po = 8/10; pe = (4*3 + 4*4 + 2*3)/100 = 0.34
# kappa = (0.8 - 0.34) / 0.66 = 0.696969...
EXPERT = {f's{i}': lab for i, lab in enumerate(
    ['claim'] * 4 + ['evidence'] * 4 + ['other'] * 2)}
LLM = {f's{i}': lab for i, lab in enumerate(
    ['claim', 'claim', 'claim', 'evidence',
     'evidence', 'evidence', 'evidence', 'other',
     'other', 'other'])}
CONFIG = {'expert': EXPERT, 'llm': LLM, 'labels': LABELS, 'n_resamples': 200}


def rows(out):
    return {r['metric']: r for r in out['metrics']}


class G01Tests(unittest.TestCase):
    def test_hand_computed_kappa_and_confusion(self):
        out = g01.run(random.Random(1), CONFIG)
        k = rows(out)['kappa_expert_llm']
        self.assertAlmostEqual(k['value'], 0.46 / 0.66, places=6)
        self.assertEqual(k['n'], 10)
        self.assertIn('method', k)
        lo, hi = k['interval']
        self.assertLessEqual(lo, hi)
        cm = out['confusion']
        self.assertEqual(cm['labels'], LABELS)
        self.assertEqual(cm['matrix'], [[3, 1, 0], [0, 3, 1], [0, 0, 2]])
        claim = cm['per_move']['claim']
        self.assertAlmostEqual(claim['precision'], 1.0)
        self.assertAlmostEqual(claim['recall'], 0.75)
        self.assertAlmostEqual(cm['per_move']['other']['precision'], 2 / 3, places=6)

    def test_perfect_agreement(self):
        out = g01.run(random.Random(0), {'expert': EXPERT, 'llm': EXPERT, 'labels': LABELS,
                                         'n_resamples': 20})
        self.assertEqual(rows(out)['kappa_expert_llm']['value'], 1.0)

    def test_self_kappa_null_without_repeat(self):
        r = rows(g01.run(random.Random(0), CONFIG))['kappa_expert_self']
        self.assertIsNone(r['value'])
        self.assertEqual(r['n'], 0)
        self.assertEqual(r['verdict_hint'], 'n/a')

    def test_self_kappa_with_repeat(self):
        out = g01.run(random.Random(0), dict(CONFIG, expert_repeat=EXPERT))
        r = rows(out)['kappa_expert_self']
        self.assertEqual((r['value'], r['n'], r['verdict_hint']), (1.0, 10, 'meets'))

    def test_other_share(self):
        r = rows(g01.run(random.Random(0), CONFIG))
        self.assertAlmostEqual(r['other_share_expert']['value'], 0.2)
        self.assertAlmostEqual(r['other_share_llm']['value'], 0.3)
        self.assertEqual(r['other_share_expert']['verdict_hint'], 'misses')

    def test_unknown_label_raises(self):
        bad = dict(LLM, s0='rebuttal')
        with self.assertRaisesRegex(ValueError, 'rebuttal'):
            g01.run(random.Random(0), dict(CONFIG, llm=bad))

    def test_missing_ids_reported(self):
        llm = {k: v for k, v in LLM.items() if k != 's9'}
        llm['x1'] = 'claim'
        out = g01.run(random.Random(0), dict(CONFIG, llm=llm))
        self.assertEqual(out['pairing']['expert_llm'],
                         {'paired': 9, 'only_expert': 1, 'only_llm': 1})
        self.assertEqual(rows(out)['kappa_expert_llm']['n'], 9)

    def test_training_split_sentence_raises(self):
        split = DocumentSplit(train_ids=['dtrain'], test_ids=['dtest'])
        doc_of = {s: 'dtest' for s in EXPERT}
        g01.run(random.Random(0), dict(CONFIG, split=split, doc_of=doc_of, n_resamples=10))
        doc_of['s3'] = 'dtrain'
        with self.assertRaises(SplitLeakError):
            g01.run(random.Random(0), dict(CONFIG, split=split, doc_of=doc_of))

    def test_deterministic(self):
        a = serialize(g01.run(random.Random(5), CONFIG))
        self.assertEqual(a, serialize(g01.run(random.Random(5), CONFIG)))

    def test_threshold_hints_both_sides(self):
        out = g01.run(random.Random(0), CONFIG)
        self.assertEqual(out['thresholds_source'], 'proposed')
        self.assertEqual(rows(out)['kappa_expert_llm']['verdict_hint'], 'meets')  # 0.697 >= 0.6
        strict = dict(CONFIG, thresholds={'kappa_expert_llm': 0.7, 'kappa_expert_self': 0.7,
                                          'other_share': 0.3})
        out = g01.run(random.Random(0), strict)
        self.assertEqual(out['thresholds_source'], 'config')
        r = rows(out)
        self.assertEqual(r['kappa_expert_llm']['verdict_hint'], 'misses')
        self.assertEqual(r['other_share_llm']['verdict_hint'], 'meets')  # 0.3 <= 0.3
        self.assertNotIn('status', out)

    def test_run_gate_refuses_without_preregistration(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(PreregistrationError):
            run_gate(g01.run, seed=0, config=CONFIG, preregistration_root=root)


if __name__ == '__main__':
    unittest.main()

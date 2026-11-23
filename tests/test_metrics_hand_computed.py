"""LLM-built, synthetic worked cases; no expert judgments or corpus inputs."""

import unittest
from unittest.mock import patch

from experiments.metrics import agreement, calibration, correction
from experiments.metrics import disagreement, preference, retrieval


class HandComputedMetricsTests(unittest.TestCase):
    def test_confusion_matrix_counts_and_order(self):
        # Pairs BA, BB, AA, BA -> first-seen B,A; BB=1, BA=2, AB=0, AA=1.
        a, b = ['B', 'B', 'A', 'B'], ['A', 'B', 'A', 'A']
        self.assertEqual(agreement.confusion_matrix(a, b),
                         (['B', 'A'], [[1, 2], [0, 1]]))
        # Reorder to A,B,C: AA=1, AB=0, BA=2, BB=1; unused C has zeros.
        self.assertEqual(agreement.confusion_matrix(a, b, ['A', 'B', 'C']),
                         (['A', 'B', 'C'], [[1, 0, 0], [2, 1, 0], [0, 0, 0]]))
        self.assertEqual(a, ['B', 'B', 'A', 'B'])
        self.assertEqual(b, ['A', 'B', 'A', 'A'])

    def test_kappa_chance_adjustment(self):
        # AA=2, AB=1, BA=0, BB=1; row totals 3,1; column totals 2,2.
        # po=3/4, pe=(3*2+1*2)/16=1/2; kappa=(3/4-1/2)/(1-1/2)=1/2.
        self.assertAlmostEqual(agreement.cohens_kappa('AAAB', 'AABB'), 0.5, places=9)
        # AB=1, BA=1 -> po=0, pe=1/2 -> kappa=-1.
        self.assertEqual(agreement.cohens_kappa('AB', 'BA'), -1.0)

    def test_per_class_precision_recall_f1(self):
        # AA=2, AB=1, BA=0, BB=1 -> A: TP=2, predicted=2, actual=3;
        # P=1, R=2/3, F1=4/5. B: TP=1, predicted=2, actual=1;
        # P=1/2, R=1, F1=2/3.
        scores = agreement.per_class_f1('AAAB', 'AABB')
        for label, expected in [('A', (1, 2 / 3, 4 / 5)), ('B', (0.5, 1, 2 / 3))]:
            for key, value in zip(('precision', 'recall', 'f1'), expected):
                self.assertAlmostEqual(scores[label][key], value, places=9)
        self.assertEqual(list(scores), ['A', 'B'])

    def test_agreement_single_class_and_zero_denominators(self):
        # AA twice -> matrix [[2]], po=pe=1: kappa convention is 1, P=R=F1=1.
        self.assertEqual(agreement.confusion_matrix('AA', 'AA'), (['A'], [[2]]))
        self.assertEqual(agreement.cohens_kappa('AA', 'AA'), 1.0)
        self.assertEqual(agreement.per_class_f1('AA', 'AA'),
                         {'A': {'precision': 1, 'recall': 1, 'f1': 1}})
        # AB twice -> A has no predictions, B no actuals, neither has TP.
        # Undefined precision/recall use 0; both F1 numerators are 0.
        self.assertEqual(agreement.per_class_f1('AA', 'BB'),
                         {label: {'precision': 0, 'recall': 0, 'f1': 0}
                          for label in 'AB'})

    def test_agreement_rejects_undefined_populations_and_labels(self):
        # n=0 or unequal paired counts cannot define agreement.
        for metric in (agreement.confusion_matrix, agreement.cohens_kappa,
                       agreement.per_class_f1):
            for a, b in [([], []), (['A'], [])]:
                with self.subTest(metric=metric.__name__, a=a, b=b):
                    with self.assertRaises(ValueError):
                        metric(a, b)
        # Duplicate axes or an omitted observed label cannot define the matrix.
        for labels in [['A', 'A'], ['B']]:
            with self.assertRaises(ValueError):
                agreement.confusion_matrix('A', 'A', labels)

    def test_reliability_bins_boundaries_and_empty_bins(self):
        # Four bins: 0 in [0,.25); .5,.5 in [.5,.75); 1 in [.75,1].
        # Counts 1,0,2,1; confidence sums 0,0,1,1; correct sums 0,0,1,1.
        # Means 0,None,.5,1 and accuracies 0,None,.5,1; no 0/0 in empty bin.
        self.assertEqual(calibration.reliability_bins([0, .5, .5, 1], [0, 1, 0, 1], 4), [
            dict(lo=0, hi=.25, count=1, mean_confidence=0, accuracy=0),
            dict(lo=.25, hi=.5, count=0, mean_confidence=None, accuracy=None),
            dict(lo=.5, hi=.75, count=2, mean_confidence=.5, accuracy=.5),
            dict(lo=.75, hi=1, count=1, mean_confidence=1, accuracy=1),
        ])

    def test_ece_weighted_gaps(self):
        # Bins [0,.5), [.5,1]: counts 1,3; means .25,.75; accuracies 0,2/3.
        # ECE=(1/4)*|0-1/4|+(3/4)*|2/3-3/4|=1/16+1/16=1/8.
        self.assertAlmostEqual(calibration.expected_calibration_error(
            [.25, .5, .75, 1], [0, 1, 0, 1], 2), .125, places=9)
        # All correct at confidence 1: occupied bin gap=|1-1|=0; empty bins omitted.
        self.assertEqual(calibration.expected_calibration_error([1, 1], [1, 1], 4), 0)

    def test_calibration_rejects_undefined_or_invalid_inputs(self):
        # n=0, unequal counts, out-of-range confidence/outcome, or invalid bin count.
        cases = [([], [], 2), ([.5], [], 2), ([-.1], [0], 2),
                 ([1.1], [1], 2), ([.5], [2], 2), ([.5], [1], 0),
                 ([.5], [1], -1), ([.5], [1], 1.5)]
        for metric in (calibration.reliability_bins, calibration.expected_calibration_error):
            for args in cases:
                with self.subTest(metric=metric.__name__, args=args):
                    with self.assertRaises(ValueError):
                        metric(*args)

    def test_recall_deduplicates_and_uses_relevant_denominator(self):
        # Prefix a,a,b contains two distinct relevant IDs out of {a,b,c}: 2/3.
        self.assertAlmostEqual(retrieval.recall_at_k(['a', 'a', 'b', 'c'],
                                                   {'a', 'b', 'c'}, 3), 2 / 3, places=9)
        # Short prefix a: one of two relevant IDs -> 1/2, regardless of k=5.
        self.assertEqual(retrieval.recall_at_k(['a'], {'a', 'b'}, 5), .5)
        # Empty ranking: zero hits / one relevant ID = 0.
        self.assertEqual(retrieval.recall_at_k([], {'a'}, 1), 0)

    def test_mean_recall_macro_average_and_skip(self):
        # Query recalls 1/2 and 1/1; third has zero relevant IDs and is skipped.
        # Macro mean=(1/2+1)/2=3/4 (not pooled 2/3); n=2, skipped=1.
        result = retrieval.mean_recall_at_k(iter([
            (['a'], {'a', 'b'}), (['c'], {'c'}), (['d'], set())]), 2)
        self.assertEqual(result, {'recall_at_k': .75, 'n': 2, 'skipped': 1})

    def test_same_move_short_prefix_and_empty(self):
        # First three A,B,A -> two matches / three available = 2/3; fourth ignored.
        self.assertAlmostEqual(retrieval.same_move_rate('ABAB', 'A', 3), 2 / 3, places=9)
        # One available A with k=5 -> 1/1=1. Empty retrieval uses the zero convention.
        self.assertEqual(retrieval.same_move_rate('A', 'A', 5), 1)
        self.assertEqual(retrieval.same_move_rate([], 'A', 5), 0)

    def test_mean_same_move_includes_empty_queries(self):
        # Rates: A vs AB -> 1/2; B vs B -> 1; A vs empty -> 0.
        # Macro mean=(1/2+1+0)/3=1/2; empty query still contributes to n=3.
        self.assertEqual(retrieval.mean_same_move_rate(iter([
            ('A', ['A', 'B']), ('B', ['B']), ('A', [])]), 5), {'rate': .5, 'n': 3})

    def test_retrieval_rejects_undefined_denominators_and_k(self):
        # Zero relevant IDs or zero included queries leaves an undefined denominator.
        calls = [(retrieval.recall_at_k, ([], set(), 1)),
                 (retrieval.mean_recall_at_k, ([], 1)),
                 (retrieval.mean_recall_at_k, ([([], set())], 1)),
                 (retrieval.mean_same_move_rate, ([], 1))]
        for k in (0, -1):
            calls.extend([(retrieval.recall_at_k, (['a'], {'a'}, k)),
                          (retrieval.mean_recall_at_k, ([(['a'], {'a'})], k)),
                          (retrieval.same_move_rate, (['A'], 'A', k)),
                          (retrieval.mean_same_move_rate, ([('A', ['A'])], k))])
        for metric, args in calls:
            with self.subTest(metric=metric.__name__, args=args):
                with self.assertRaises(ValueError):
                    metric(*args)

    def test_win_rate_half_credit_for_ties(self):
        # 2 wins, 1 loss, 1 tie -> (2+1/2)/4=5/8.
        self.assertEqual(preference.win_rate(['a', 'a', 'b', 'tie']),
                         dict(win_rate=.625, n=4, wins=2, losses=1, ties=1))
        # Single-category populations: 2 wins -> 1; 2 losses -> 0; 2 ties -> 1/2.
        for choice, expected in [('a', 1), ('b', 0), ('tie', .5)]:
            self.assertEqual(preference.win_rate([choice, choice])['win_rate'], expected)

    def test_bootstrap_interpolates_hand_selected_resamples(self):
        # a,b,tie -> category indices 0,1,2. Controlled legal replacement draws:
        # bbb, abt, aaa -> half-win totals 0,3,6 -> sorted rates 0,1/2,1.
        # confidence=.5 -> tail=.25, ranks .5 and 1.5 -> bounds .25 and .75.
        with patch('experiments.metrics.preference.random.Random') as random_class:
            rng = random_class.return_value
            rng.randrange.side_effect = [1, 1, 1, 0, 1, 2, 0, 0, 0]
            self.assertEqual(preference.bootstrap_interval(
                ['a', 'b', 'tie'], n_resamples=3, confidence=.5, seed=7), (.25, .75))
            random_class.assert_called_once_with(7)
            self.assertEqual(rng.randrange.call_count, 9)
            self.assertTrue(all(call.args == (3,) for call in rng.randrange.call_args_list))

    def test_bootstrap_single_category_real_rng(self):
        # Every replacement replicate of aa, bb, or tie,tie has rate 1, 0, or 1/2.
        # All percentile ranks therefore return that same rate, including one replicate.
        for choice, expected in [('a', 1), ('b', 0), ('tie', .5)]:
            for count in (1, 9):
                self.assertEqual(preference.bootstrap_interval(
                    [choice, choice], n_resamples=count), (expected, expected))

    def test_preference_rejects_undefined_populations_and_intervals(self):
        # n=0 cannot define a rate; unknown category cannot be tallied.
        for metric in (preference.win_rate, preference.bootstrap_interval):
            for choices in ([], ['unknown']):
                with self.assertRaises(ValueError):
                    metric(choices)
        # Zero replicates gives no percentiles; confidence must be strictly between 0 and 1.
        for kwargs in ({'n_resamples': 0}, {'confidence': 0}, {'confidence': 1}):
            with self.assertRaises(ValueError):
                preference.bootstrap_interval(['a'], **kwargs)

    def test_layer_disagreement_uses_slow_reference(self):
        # (fast,slow): AA,BA,BB,CB -> 2/4 unequal overall.
        # Slow A: 1/2 unequal; slow B: 1/2 unequal; fast-only C is not a group.
        self.assertEqual(disagreement.layer_disagreement(iter([
            ('A', 'A'), ('B', 'A'), ('B', 'B'), ('C', 'B')])),
            {'rate': .5, 'n': 4, 'disagreements': 2, 'per_move': {
                'A': {'rate': .5, 'n': 2, 'disagreements': 1},
                'B': {'rate': .5, 'n': 2, 'disagreements': 1}}})
        # Single label AA: zero unequal / one pair = 0.
        self.assertEqual(disagreement.layer_disagreement([('A', 'A')]),
                         {'rate': 0, 'n': 1, 'disagreements': 0,
                          'per_move': {'A': {'rate': 0, 'n': 1, 'disagreements': 0}}})

    def test_correction_rate_exact_strings_and_repeated_entries(self):
        # Five equal-weight entries: unchanged, case change, whitespace change,
        # Unicode normalization change, unchanged -> 3/5 overall.
        # d1: 2/3; d2: 1/2. Move A: 1/3; B: 2/2. Repeated d1/A counts twice.
        rows = [('d1', 'A', 'x', 'x'), ('d1', 'A', 'x', 'X'),
                ('d1', 'B', 'x', 'x '), ('d2', 'B', '\u00e9', 'e\u0301'),
                ('d2', 'A', '', '')]
        entries = (dict(draft=d, move=m, candidate=c, final=f, ignored=True)
                   for d, m, c, f in rows)
        result = correction.correction_rate(entries)
        self.assertAlmostEqual(result['rate'], .6, places=9)
        self.assertEqual(result['n'], 5)
        for group, expected in [('per_draft', {'d1': (2 / 3, 3), 'd2': (.5, 2)}),
                                ('per_move', {'A': (1 / 3, 3), 'B': (1, 2)})]:
            self.assertEqual(set(result[group]), set(expected))
            for key, (rate, n) in expected.items():
                self.assertAlmostEqual(result[group][key]['rate'], rate, places=9)
                self.assertEqual(result[group][key]['n'], n)
        # One unchanged entry: 0/1=0 in overall, draft and move populations.
        self.assertEqual(correction.correction_rate([
            dict(draft='d', move='A', candidate='x', final='x')]),
            {'rate': 0, 'n': 1, 'per_draft': {'d': {'rate': 0, 'n': 1}},
             'per_move': {'A': {'rate': 0, 'n': 1}}})

    def test_disagreement_and_correction_reject_empty_or_missing_data(self):
        # Zero entries -> denominator 0, explicitly rejected by both metrics.
        for metric in (disagreement.layer_disagreement, correction.correction_rate):
            with self.assertRaises(ValueError):
                metric(iter([]))
        # Removing each required field leaves the grouping or comparison undefined.
        entry = dict(draft='d', move='A', candidate='x', final='y')
        for missing in entry:
            with self.assertRaises(ValueError):
                correction.correction_rate([{k: v for k, v in entry.items() if k != missing}])


if __name__ == '__main__':
    unittest.main()

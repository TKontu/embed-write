"""Synthetic, hand-computed agreement cases; no expert/corpus judgments."""

import unittest

from experiments.metrics.agreement import confusion_matrix, cohens_kappa, per_class_f1


class AgreementTests(unittest.TestCase):
    def test_counts_and_first_seen_label_order(self):
        # Pairs (b,a), (a,a), (b,c): rows b,a,c; columns b,a,c.
        self.assertEqual(
            confusion_matrix(['b', 'a', 'b'], ['a', 'a', 'c']),
            (['b', 'a', 'c'], [[0, 1, 1], [0, 1, 0], [0, 0, 0]]),
        )

    def test_explicit_order_and_unused_label(self):
        # One a->b observation; unused c has a zero row and column.
        self.assertEqual(confusion_matrix(['a'], ['b'], ['c', 'b', 'a']),
                         (['c', 'b', 'a'], [[0, 0, 0], [0, 0, 0], [0, 1, 0]]))

    def test_rejects_invalid_labels(self):
        for labels in ([], ['a'], ['a', 'b', 'a']):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                confusion_matrix(['a'], ['b'], labels)

    def test_rejects_empty_and_unequal_sequences(self):
        for a, b in (([], []), ([], ['a']), (['a'], []),
                     (['a'], ['a', 'b']), (['a', 'b'], ['a'])):
            for metric in (confusion_matrix, cohens_kappa, per_class_f1):
                with self.subTest(metric=metric.__name__, a=a, b=b):
                    with self.assertRaises(ValueError):
                        metric(a, b)

    def test_kappa_hand_computed_two_rater_table(self):
        # Table [[20, 5], [10, 15]], n=50: po=35/50=.7;
        # pe=(25*30 + 25*20)/2500=.5; kappa=(.7-.5)/(.5)=.4.
        a = ['yes'] * 25 + ['no'] * 25
        b = ['yes'] * 20 + ['no'] * 5 + ['yes'] * 10 + ['no'] * 15
        self.assertAlmostEqual(cohens_kappa(a, b), 0.4, delta=1e-9)

    def test_kappa_perfect_and_degenerate_agreement(self):
        # po=1 yields kappa=1; pe=1 is defined as 1 for the constant case.
        for labels in (['a', 'b', 'a'], ['a'], ['a', 'a']):
            with self.subTest(labels=labels):
                self.assertEqual(cohens_kappa(labels, labels), 1.0)

    def test_kappa_negative_and_zero_agreement(self):
        # Balanced reversed labels: po=0, pe=1/2, kappa=-1.
        self.assertEqual(cohens_kappa(['a', 'b'], ['b', 'a']), -1.0)
        # Different constant labels: po=pe=0, kappa=0.
        self.assertEqual(cohens_kappa(['a', 'a'], ['b', 'b']), 0.0)

    def test_per_class_precision_recall_f1(self):
        # [[2,1],[0,1]]: a precision=2/2, recall=2/3, F1=4/5;
        # b precision=1/2, recall=1/1, F1=2/3.
        result = per_class_f1(['a', 'a', 'a', 'b'], ['a', 'a', 'b', 'b'])
        self.assertEqual(list(result), ['a', 'b'])
        self.assertEqual(result['a'], {'precision': 1.0, 'recall': 2/3, 'f1': 4/5})
        self.assertEqual(result['b'], {'precision': 1/2, 'recall': 1.0, 'f1': 2/3})

    def test_classes_absent_from_predictions_or_gold(self):
        # a TP=1, predicted=2, gold=2: P=R=F1=1/2.
        # b has no predictions; c has no gold: each has TP=0, F1=0.
        self.assertEqual(
            per_class_f1(['a', 'a', 'b'], ['a', 'c', 'a']),
            {'a': {'precision': .5, 'recall': .5, 'f1': .5},
             'c': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0},
             'b': {'precision': 0.0, 'recall': 0.0, 'f1': 0.0}},
        )

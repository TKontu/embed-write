"""LLM-built synthetic rewrite pairs with hand-computed arithmetic; no corpus or expert data."""

import unittest

from experiments.metrics.meaning import (
    RewritePair, calibrate, combine, number_unit_arm, score, wilson)


def P(i, keep, o="a", c="a"):
    return RewritePair(str(i), o, c, keep)


def table(mapping):
    return lambda o, c: mapping[o]


class MeaningTests(unittest.TestCase):
    def test_number_arm_flags_changed_number_and_unit(self):
        self.assertEqual(number_unit_arm("It weighs 5 kg.", "The weight is 5 kg."), 1.0)
        self.assertEqual(number_unit_arm("It weighs 5 kg.", "It weighs 6 kg."), 0.0)
        self.assertEqual(number_unit_arm("It weighs 5 kg.", "It weighs 5 g."), 0.0)

    def test_balanced_accuracy_hand_computed(self):
        # preserved: scores 1,1,0 -> TPR 2/3; not preserved: 0,0,1,1 -> TNR 2/4.
        scores = {"p1": 1.0, "p2": 1.0, "p3": 0.0, "n1": 0.0, "n2": 0.0, "n3": 1.0, "n4": 1.0}
        pairs = [P(k, k.startswith("p"), o=k) for k in scores]
        r = score(pairs, table(scores), 0.5)
        self.assertAlmostEqual(r.tpr.value, 2 / 3)
        self.assertEqual((r.tpr.n, r.tnr.n, r.n), (3, 4, 7))
        self.assertAlmostEqual(r.tnr.value, 0.5)
        self.assertAlmostEqual(r.balanced_accuracy, (2 / 3 + 0.5) / 2)
        self.assertEqual(r.tpr.interval, wilson(2, 3))
        lo, hi = wilson(2, 4)
        self.assertTrue(lo < 0.5 < hi)

    def test_calibrate_lowest_threshold(self):
        scores = {"n1": 0.1, "n2": 0.2, "p1": 0.3, "p2": 0.9}
        pairs = [P(k, k.startswith("p"), o=k) for k in scores]
        c = calibrate(pairs, table(scores), 0.95)
        # t=0.1 flags nothing; t=0.2 flags n1 (1/1) -> lowest qualifying.
        self.assertEqual((c.threshold, c.precision, c.n_flagged, c.n), (0.2, 1.0, 1, 4))

    def test_calibrate_none_when_unreachable(self):
        scores = {"p1": 0.1, "n1": 0.5, "p2": 0.9}
        pairs = [P(k, k.startswith("p"), o=k) for k in scores]
        self.assertIsNone(calibrate(pairs, table(scores), 0.95))

    def test_empty_pairs_raise(self):
        with self.assertRaises(ValueError):
            score([], number_unit_arm, 0.5)
        with self.assertRaises(ValueError):
            calibrate([], number_unit_arm)

    def test_out_of_range_arm_raises(self):
        for bad in (1.5, -0.1, float("nan")):
            with self.assertRaises(ValueError):
                score([P(1, True)], lambda o, c, b=bad: b, 0.5)

    def test_combine_weighted_mean_and_validation(self):
        arm = combine([lambda o, c: 1.0, lambda o, c: 0.0], [3, 1])
        self.assertAlmostEqual(arm("x", "y"), 0.75)
        for arms, w in (([number_unit_arm], [1, 2]), ([number_unit_arm], [-1]),
                        ([number_unit_arm], [0]), ([], []),
                        ([number_unit_arm], [float("inf")])):
            with self.assertRaises(ValueError):
                combine(arms, w)


if __name__ == "__main__":
    unittest.main()

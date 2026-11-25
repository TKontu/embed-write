import dataclasses
import unittest

from analysis.register_features import (
    FEATURES,
    FeatureComparison,
    FeatureReport,
    SetSummary,
    compare,
    sentence_features,
)


class FeatureCountTests(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(sentence_features("The cat sat on the mat.")["words"], 6)
        self.assertEqual(sentence_features("")["words"], 0)

    def test_hedges_case_insensitive_and_word_boundary(self):
        f = sentence_features("It MAY rain; results Suggest it could possibly work.")
        self.assertEqual(f["hedges"], 4)
        self.assertEqual(sentence_features("The mayor appeared likely.")["hedges"], 2)
        self.assertEqual(sentence_features("The mayor spoke.")["hedges"], 0)

    def test_passive_positive_and_negative(self):
        self.assertEqual(sentence_features("The plan was approved.")["passive"], 1)
        self.assertEqual(sentence_features("This method is widely used.")["passive"], 1)
        self.assertEqual(sentence_features("The paper was written by her.")["passive"], 1)
        self.assertEqual(sentence_features("She was happy.")["passive"], 0)
        self.assertEqual(sentence_features("They approved the plan.")["passive"], 0)

    def test_numbers(self):
        self.assertEqual(sentence_features("Rates rose 3.5% to 12 units in 2020.")["numbers"], 3)
        self.assertEqual(sentence_features("No figures here.")["numbers"], 0)

    def test_connectives_multiword_and_punctuation(self):
        f = sentence_features("However, prices fell. As a result, demand rose; therefore it ended.")
        self.assertEqual(f["connectives"], 3)
        self.assertEqual(sentence_features("In addition, MOREOVER we left.")["connectives"], 2)
        self.assertEqual(sentence_features("Thereforex is not a word.")["connectives"], 0)


class CompareTests(unittest.TestCase):
    def test_means_medians_diffs_and_d(self):
        a = ["one two", "one two three four"]  # words 2, 4
        b = ["a b c d e f", "a b c d e f g h", "a b c d e f g h i j"]  # 6, 8, 10
        report = compare(iter(a), (s for s in b))
        w = report.feature("words")
        self.assertEqual((w.a.n, w.b.n), (2, 3))
        self.assertAlmostEqual(w.a.mean, 3.0)
        self.assertAlmostEqual(w.a.median, 3.0)
        self.assertAlmostEqual(w.b.mean, 8.0)
        self.assertAlmostEqual(w.b.median, 8.0)
        self.assertAlmostEqual(w.mean_diff, 5.0)
        # pooled var = ((1*2) + (2*4)) / 3 = 10/3
        self.assertAlmostEqual(w.cohens_d, 5.0 / (10 / 3) ** 0.5)

    def test_d_none_cases_and_empty(self):
        same = compare(["a b", "c d"], ["a b c", "d e f"])
        self.assertIsNone(same.feature("words").cohens_d)
        self.assertAlmostEqual(same.feature("words").mean_diff, 1.0)
        small = compare(["a b"], ["a b c", "d e f g"])
        self.assertIsNone(small.feature("words").cohens_d)
        empty = compare([], ["a b"])
        w = empty.feature("words")
        self.assertEqual(w.a.n, 0)
        self.assertIsNone(w.a.mean)
        self.assertIsNone(w.a.median)
        self.assertIsNone(w.mean_diff)
        self.assertIsNone(w.cohens_d)

    def test_no_aggregate_score_field(self):
        names = {f.name for f in dataclasses.fields(FeatureReport)}
        self.assertEqual(names, {"features"})
        for cls in (FeatureComparison, SetSummary):
            for field in dataclasses.fields(cls):
                self.assertNotIn(field.name, {"score", "total", "aggregate", "verdict"})

    def test_sorted_by_abs_d_display_only(self):
        report = compare(["a b", "a b c d", "x"], ["a b c d e f", "a b c d e f g h", "y z"])
        self.assertEqual({c.name for c in report.features}, set(FEATURES))
        ordered = report.sorted_by_effect()
        ds = [abs(c.cohens_d) for c in ordered if c.cohens_d is not None]
        self.assertEqual(ds, sorted(ds, reverse=True))
        self.assertEqual(len(ordered), len(FEATURES))


if __name__ == "__main__":
    unittest.main()

import unittest
from collections import Counter

from service.support_check import extract_support, support_diff


class SupportCheckTest(unittest.TestCase):
    def test_identical_text_preserved(self):
        text = "The rig weighs 5 kg and costs 1,200 [docs](https://ex.org/a) [@smith2020]."
        diff = support_diff(text, text)
        self.assertTrue(diff.preserved)
        self.assertEqual(diff.missing, Counter())

    def test_reworded_same_support_preserved(self):
        a = "It weighs 5 kg, runs at 3.2% load, see [the paper](https://ex.org/p) [@lee]."
        b = "At 3.2% load it weighs 5kg; the [source](https://ex.org/p) agrees [@lee]."
        self.assertTrue(support_diff(a, b).preserved)

    def test_altered_value(self):
        diff = support_diff("It weighs 5 kg.", "It weighs 6 kg.")
        self.assertEqual(diff.missing, Counter({"num:5 kg": 1}))
        self.assertEqual(diff.added, Counter({"num:6 kg": 1}))
        self.assertFalse(diff.preserved)

    def test_changed_unit(self):
        diff = support_diff("It weighs 5 kg.", "It weighs 5 g.")
        self.assertEqual(diff.missing, Counter({"num:5 kg": 1}))
        self.assertEqual(diff.added, Counter({"num:5 g": 1}))

    def test_dropped_percentage(self):
        diff = support_diff("Growth was 12% this year.", "Growth was strong this year.")
        self.assertEqual(diff.missing, Counter({"num:12%": 1}))
        self.assertEqual(diff.added, Counter())

    def test_changed_decimal(self):
        diff = support_diff("Latency fell to 3.25 ms.", "Latency fell to 3.2 ms.")
        self.assertEqual(diff.missing, Counter({"num:3.25 ms": 1}))
        self.assertEqual(diff.added, Counter({"num:3.2 ms": 1}))

    def test_changed_link_target(self):
        diff = support_diff("See [x](https://a.org/1).", "See [x](https://a.org/2).")
        self.assertEqual(diff.missing, Counter({"link:https://a.org/1": 1}))
        self.assertEqual(diff.added, Counter({"link:https://a.org/2": 1}))

    def test_bare_url_changed(self):
        diff = support_diff("Ref https://a.org/x.", "Ref https://b.org/x.")
        self.assertEqual(diff.missing, Counter({"link:https://a.org/x": 1}))

    def test_dropped_citation_key(self):
        diff = support_diff("As shown [@a; @b].", "As shown [@a].")
        self.assertEqual(diff.missing, Counter({"cite:b": 1}))
        self.assertEqual(diff.added, Counter())

    def test_reordered_numbers_preserved(self):
        self.assertTrue(support_diff("From 3 to 7 then 10 °C.", "10 °C, then 7, from 3.").preserved)

    def test_dropped_duplicate_detected(self):
        diff = support_diff("Scores were 4, 4 and 9.", "Scores were 4 and 9.")
        self.assertEqual(diff.missing, Counter({"num:4": 1}))
        self.assertFalse(diff.preserved)

    def test_thousands_separator_equal(self):
        self.assertTrue(support_diff("About 1,000 users.", "About 1000 users.").preserved)
        self.assertEqual(extract_support("1,000,000"), Counter({"num:1000000": 1}))

    def test_signed_numbers(self):
        self.assertEqual(extract_support("from -5 °C to +3"), Counter({"num:-5 °C": 1, "num:3": 1}))
        self.assertFalse(support_diff("-5 °C", "5 °C").preserved)

    def test_url_digits_not_numbers(self):
        self.assertEqual(extract_support("https://ex.org/v2/123"),
                         Counter({"link:https://ex.org/v2/123": 1}))

    def test_no_support_tokens_preserved(self):
        diff = support_diff("A plain sentence.", "Another plain sentence.")
        self.assertTrue(diff.preserved)

    def test_leading_currency_changed(self):
        diff = support_diff("It costs $5.", "It costs €5.")
        self.assertEqual(diff.missing, Counter({"num:5 $": 1}))
        self.assertEqual(diff.added, Counter({"num:5 €": 1}))

    def test_leading_equals_trailing_currency(self):
        self.assertTrue(support_diff("It costs $5.", "It costs 5 $.").preserved)

    def test_leading_currency_forms(self):
        self.assertEqual(
            extract_support("€ 1,200.50 and -$3 and £7"),
            Counter({"num:1200.50 €": 1, "num:-3 $": 1, "num:7 £": 1}),
        )

    def test_bare_number_without_currency(self):
        self.assertEqual(extract_support("about 5 items"), Counter({"num:5": 1}))

    def test_non_adjacent_currency_ignored(self):
        self.assertEqual(extract_support("paid in $ about 5"), Counter({"num:5": 1}))
        self.assertEqual(extract_support("$ alone"), Counter())


if __name__ == "__main__":
    unittest.main()

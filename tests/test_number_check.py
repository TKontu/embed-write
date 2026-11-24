import unittest

from service.number_check import check_numbers


class NumberCheckTest(unittest.TestCase):
    def test_all_matched_reports_source_ids(self):
        r = check_numbers("We carried 15 kg over 5 km.", [("s1", "Load: 15 kg."), ("s2", "Route 5 km long.")])
        self.assertEqual(r.unmatched, ())
        self.assertEqual(r.matches, {"num:15 kg": ("s1",), "num:5 km": ("s2",)})
        self.assertTrue(r.all_matched)

    def test_altered_value_and_unit_unmatched(self):
        r = check_numbers("12 kg and 5 km", [("s1", "15 kg and 5 m")])
        self.assertEqual(r.unmatched, ("num:12 kg", "num:5 km"))
        self.assertEqual(r.matches["num:12 kg"], ())
        self.assertFalse(r.all_matched)

    def test_number_in_two_sources_lists_both(self):
        r = check_numbers("42 items", [("a", "42 items"), ("b", "none"), ("c", "about 42 items")])
        self.assertEqual(r.matches["num:42"], ("a", "c"))

    def test_presence_semantics(self):
        r = check_numbers("3 h then 3 h again", [("s", "3 h")])
        self.assertEqual(r.unmatched, ())
        self.assertEqual(list(r.matches), ["num:3 h"])

    def test_empty_draft_and_no_sources(self):
        self.assertEqual(check_numbers("", [("s", "5 kg")]).matches, {})
        self.assertTrue(check_numbers("no numbers", []).all_matched)
        r = check_numbers("7 kg", [])
        self.assertEqual(r.unmatched, ("num:7 kg",))

    def test_url_numbers_ignored(self):
        r = check_numbers("See https://x.org/2024/99 and [d](http://y.io/7).", [])
        self.assertEqual(r.matches, {})
        r = check_numbers("10 kg", [("s", "https://z.org/10")])
        self.assertEqual(r.unmatched, ("num:10 kg",))


if __name__ == "__main__":
    unittest.main()

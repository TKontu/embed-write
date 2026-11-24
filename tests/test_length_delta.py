import dataclasses
import unittest

from service.length_delta import LengthDelta, count_words, length_delta


class LengthDeltaTest(unittest.TestCase):
    def test_equal_texts(self):
        d = length_delta("The cat sat.", "The cat sat.")
        self.assertEqual((d.original_words, d.candidate_words, d.word_delta), (3, 3, 0))
        self.assertEqual(d.char_delta, 0)
        self.assertEqual(d.word_ratio, 1.0)
        self.assertEqual(d.char_ratio, 1.0)

    def test_longer_candidate(self):
        d = length_delta("one two", "one two three four")
        self.assertEqual(d.word_delta, 2)
        self.assertEqual(d.word_ratio, 2.0)
        self.assertEqual(d.original_chars, 7)
        self.assertEqual(d.candidate_chars, 18)
        self.assertEqual(d.char_delta, 11)

    def test_shorter_candidate(self):
        d = length_delta("one two three four", "one two")
        self.assertEqual(d.word_delta, -2)
        self.assertEqual(d.word_ratio, 0.5)
        self.assertLess(d.char_delta, 0)

    def test_empty_original_ratio_none(self):
        d = length_delta("", "new words")
        self.assertEqual(d.original_words, 0)
        self.assertEqual(d.word_delta, 2)
        self.assertIsNone(d.word_ratio)
        self.assertIsNone(d.char_ratio)

    def test_whitespace_only_and_surrounding_whitespace(self):
        d = length_delta("   \n\t ", "  hi  ")
        self.assertEqual((d.original_words, d.original_chars), (0, 0))
        self.assertEqual(d.candidate_chars, 2)
        self.assertIsNone(d.char_ratio)

    def test_unicode(self):
        d = length_delta("Hyvää päivää", "naïve café über")
        self.assertEqual(d.original_words, 2)
        self.assertEqual(d.candidate_words, 3)
        self.assertEqual(d.original_chars, 12)

    def test_markdown_punctuation_and_compounds(self):
        self.assertEqual(count_words("## **Bold** - _it_ > `x` *"), 3)
        self.assertEqual(count_words("well-known don't it’s"), 3)

    def test_no_judging_fields(self):
        names = {f.name for f in dataclasses.fields(LengthDelta)} | set(dir(LengthDelta))
        for bad in ("pass", "ok", "threshold", "score", "passed", "verdict"):
            self.assertFalse(any(bad in n.lower() for n in names if not n.startswith("__")), bad)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            length_delta("a", "b").word_delta = 5


if __name__ == "__main__":
    unittest.main()

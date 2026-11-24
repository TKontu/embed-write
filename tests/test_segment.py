"""Synthetic, offline CK-02 acceptance checks (no corpus/model required)."""
import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("pysbd"),
                     "pysbd is not installed; run CLAUDE.md install in .venv")
class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("service.segment"),
                             "CK-02 sentence segmenter is not implemented")
        from service.segment import segment_sentences
        self.segment = segment_sentences

    def test_empty_and_whitespace(self):
        for text in ("", " \t\n"):
            with self.subTest(text=text):
                self.assertEqual(self.segment(text), ())

    def test_abbreviations(self):
        self.assertEqual(self.segment("Dr. Smith arrived, i.e. came here. Next."),
                         ("Dr. Smith arrived, i.e. came here.", "Next."))

    def test_decimals(self):
        self.assertEqual(self.segment("It is 3.14 today. Next."),
                         ("It is 3.14 today.", "Next."))

    def test_units(self):
        self.assertEqual(self.segment("It measured 5 mm. Next sample."),
                         ("It measured 5 mm.", "Next sample."))

    def test_quotations(self):
        self.assertEqual(self.segment('He said, "Go now." Then left.'),
                         ('He said, "Go now."', 'Then left.'))

    def test_inline_code(self):
        self.assertEqual(self.segment("Use `a. B! C?` here. Next."),
                         ("Use `a. B! C?` here.", "Next."))

    def test_multiple_code_spans(self):
        self.assertEqual(self.segment("Use `a. B` and `c? D` here. Next."),
                         ("Use `a. B` and `c? D` here.", "Next."))

    def test_footnotes_after_terminal_punctuation(self):
        for marker in ("[^1]", "¹", "[^1]²", "[^12]", "¹²"):
            with self.subTest(marker=marker):
                self.assertEqual(self.segment("Done." + marker + " Next."),
                                 ("Done." + marker, "Next."))

    def test_footnotes_inside_sentence(self):
        self.assertEqual(self.segment("A claim[^1] and another¹ hold. Next."),
                         ("A claim[^1] and another¹ hold.", "Next."))

    def test_marker_only_and_leading_marker_text_is_preserved(self):
        for text in ("[^1]", "¹", "[^1] A claim.", "¹ A claim."):
            with self.subTest(text=text):
                self.assertEqual(self.segment(text), (text,))

    def test_code_with_footnotes_and_newlines_is_preserved(self):
        text = "Use `a.[^1]\n B!` here.[^2] Next."
        self.assertEqual(self.segment(text),
                         ("Use `a.[^1]\n B!` here.[^2]", "Next."))

    def test_cache_connection(self):
        from service.segment import SEGMENTER_ID
        from service.segcache import SegmentationCache
        cache = SegmentationCache(self.segment, 2, key_version=SEGMENTER_ID)
        self.assertEqual(cache.get("One. Two."), ("One.", "Two."))
        self.assertEqual(cache.get("One. Two."), ("One.", "Two."))
        self.assertEqual(cache.stats().hits, 1)

    def test_preserves_internal_whitespace(self):
        self.assertEqual(self.segment("  A  small test.  Next.\n"),
                         ("A  small test.", "Next."))


if __name__ == "__main__":
    unittest.main()

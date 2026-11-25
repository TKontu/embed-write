import json
import unittest
from pathlib import Path

from service.sentence_keys import sentence_keys


class SentenceKeysTest(unittest.TestCase):
    def test_key_format(self):
        self.assertEqual(sentence_keys("b1", ["aa", "bb"]), ("b1:aa", "b1:bb"))

    def test_empty_sentences(self):
        self.assertEqual(sentence_keys("b1", []), ())

    def test_stability(self):
        hashes = ["aa", "bb", "aa", "cc"]
        self.assertEqual(sentence_keys("b1", hashes), sentence_keys("b1", list(hashes)))

    def test_edit_changes_only_that_key(self):
        before = sentence_keys("b1", ["aa", "bb", "cc"])
        after = sentence_keys("b1", ["aa", "xx", "cc"])
        self.assertEqual((before[0], before[2]), (after[0], after[2]))
        self.assertNotEqual(before[1], after[1])

    def test_insert_leaves_other_keys(self):
        before = sentence_keys("b1", ["aa", "bb"])
        after = sentence_keys("b1", ["aa", "nn", "bb"])
        self.assertEqual(after, (before[0], "b1:nn", before[1]))

    def test_duplicates_get_suffixes(self):
        self.assertEqual(
            sentence_keys("b1", ["aa", "aa", "bb", "aa"]),
            ("b1:aa", "b1:aa#1", "b1:bb", "b1:aa#2"),
        )

    def test_insert_duplicate_before_shifts_suffixes(self):
        # Documents the residual: repeat keys depend on order in the block.
        before = sentence_keys("b1", ["bb", "aa"])
        after = sentence_keys("b1", ["aa", "bb", "aa"])
        self.assertEqual(before[1], "b1:aa")
        self.assertEqual(after, ("b1:aa", "b1:bb", "b1:aa#1"))

    def test_value_errors(self):
        for block_id, hashes in [
            ("", ["aa"]),
            ("b1", [""]),
            ("b1", ["a:a"]),
            ("b1", ["a#a"]),
            ("b1", ["ok", "bad#"]),
        ]:
            with self.subTest(block_id=block_id, hashes=hashes):
                with self.assertRaises(ValueError):
                    sentence_keys(block_id, hashes)

    def test_block_ids_disjoint(self):
        hashes = ["aa", "aa", "bb"]
        self.assertFalse(set(sentence_keys("b1", hashes)) & set(sentence_keys("b2", hashes)))


FIXTURE = Path(__file__).resolve().parents[1] / "docmodel" / "test" / "fixtures" / "sentence-keys.json"


class SentenceKeysFixtureParityTest(unittest.TestCase):
    def test_matches_shared_fixture(self):
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertTrue(any("#" in k for c in cases for k in c["keys"]))
        for case in cases:
            with self.subTest(block_id=case["block_id"], keys=case["keys"]):
                self.assertEqual(sentence_keys(case["block_id"], case["hashes"]), tuple(case["keys"]))



if __name__ == "__main__":
    unittest.main()

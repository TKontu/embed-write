import dataclasses
import unittest

from service.word_diff import DiffOp, proposal_diffs, word_diff

KINDS = {"equal", "delete", "insert", "replace"}


def kinds(ops):
    return [op.kind for op in ops]


class WordDiffTest(unittest.TestCase):
    def test_identical_texts_single_equal_op(self):
        ops = word_diff("The cat sat.", "The cat sat.")
        self.assertEqual(ops, (DiffOp("equal", "The cat sat.", "The cat sat."),))

    def test_identical_whitespace_only_text(self):
        ops = word_diff("   \n\t ", "   \n\t ")
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].kind, "equal")

    def test_both_empty_gives_empty_tuple(self):
        self.assertEqual(word_diff("", ""), ())

    def test_one_word_changed_is_one_replace(self):
        ops = word_diff("The cat sat.", "The dog sat.")
        self.assertEqual(kinds(ops), ["equal", "replace", "equal"])
        self.assertEqual(ops[0], DiffOp("equal", "The ", "The "))
        self.assertEqual(ops[1], DiffOp("replace", "cat ", "dog "))
        self.assertEqual(ops[2], DiffOp("equal", "sat.", "sat."))

    def test_insert_at_start(self):
        ops = word_diff("b c", "a b c")
        self.assertEqual(kinds(ops), ["insert", "equal"])
        self.assertEqual(ops[0], DiffOp("insert", "", "a "))
        self.assertEqual(ops[1].original_text, "b c")
        self.assertEqual(ops[1].candidate_text, "b c")

    def test_delete_at_start(self):
        ops = word_diff("a b c", "b c")
        self.assertEqual(kinds(ops), ["delete", "equal"])
        self.assertEqual(ops[0], DiffOp("delete", "a ", ""))
        self.assertEqual(ops[1].original_text, "b c")

    def test_insert_in_middle(self):
        ops = word_diff("a c", "a b c")
        self.assertEqual(kinds(ops), ["equal", "insert", "equal"])
        self.assertEqual(ops[1], DiffOp("insert", "", "b "))

    def test_delete_in_middle(self):
        ops = word_diff("a b c", "a c")
        self.assertEqual(kinds(ops), ["equal", "delete", "equal"])
        self.assertEqual(ops[1], DiffOp("delete", "b ", ""))

    def test_insert_at_end(self):
        # Trailing whitespace belongs to the preceding word, so an appended
        # word is a separate insert only when the shared prefix ends at a
        # token boundary.
        ops = word_diff("alpha beta ", "alpha beta gamma ")
        self.assertEqual(kinds(ops), ["equal", "insert"])
        self.assertEqual(ops[0], DiffOp("equal", "alpha beta ", "alpha beta "))
        self.assertEqual(ops[1], DiffOp("insert", "", "gamma "))

    def test_delete_at_end(self):
        ops = word_diff("alpha beta gamma ", "alpha beta ")
        self.assertEqual(kinds(ops), ["equal", "delete"])
        self.assertEqual(ops[0], DiffOp("equal", "alpha beta ", "alpha beta "))
        self.assertEqual(ops[1], DiffOp("delete", "gamma ", ""))

    def test_both_sides_empty_text_against_words(self):
        self.assertEqual(
            word_diff("", "one two"),
            (DiffOp("insert", "", "one two"),),
        )
        self.assertEqual(
            word_diff("one two", ""),
            (DiffOp("delete", "one two", ""),),
        )

    def test_punctuation_change(self):
        ops = word_diff("Stop!", "Stop.")
        self.assertEqual(kinds(ops), ["replace"])
        self.assertEqual(ops[0].original_text, "Stop!")
        self.assertEqual(ops[0].candidate_text, "Stop.")

    def test_whitespace_difference_attaches_to_the_word(self):
        ops = word_diff("one  two", "one two")
        self.assertEqual(kinds(ops), ["replace", "equal"])
        self.assertEqual(ops[0], DiffOp("replace", "one  ", "one "))
        self.assertEqual(ops[1], DiffOp("equal", "two", "two"))

    def test_ops_are_frozen_and_returned_as_tuple(self):
        ops = word_diff("a", "b")
        self.assertIsInstance(ops, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ops[0].kind = "equal"


class WordDiffPropertiesTest(unittest.TestCase):
    PAIRS = [
        ("", ""),
        ("", "new words here"),
        ("old words here", ""),
        ("", "   "),
        ("   ", ""),
        ("one", "one"),
        ("Hello, world!", "Hello, brave world!"),
        ("a  b\tc", "a b\tc"),
        ("line one\nline two\n", "line one\nline three\n"),
        ("naïve café — “quoted”", "naive cafe — \"quoted\""),
        ("...", "…"),
        ("  leading", "leading  "),
        ("trailing spaces   ", "trailing spaces"),
        ("The cat sat on the mat.", "The dog sat on the mat, quietly."),
        ("one\ntwo\n\nthree", "one\ntwo\nthree"),
    ]

    def test_round_trip_and_well_formedness(self):
        for original, candidate in self.PAIRS:
            with self.subTest(original=original, candidate=candidate):
                ops = word_diff(original, candidate)
                self.assertIsInstance(ops, tuple)
                self.assertEqual("".join(op.original_text for op in ops), original)
                self.assertEqual("".join(op.candidate_text for op in ops), candidate)
                for op in ops:
                    self.assertIn(op.kind, KINDS)
                    if op.kind == "equal":
                        self.assertNotEqual(op.original_text, "")
                        self.assertEqual(op.original_text, op.candidate_text)
                    elif op.kind == "delete":
                        self.assertNotEqual(op.original_text, "")
                        self.assertEqual(op.candidate_text, "")
                    elif op.kind == "insert":
                        self.assertEqual(op.original_text, "")
                        self.assertNotEqual(op.candidate_text, "")
                    else:
                        self.assertNotEqual(op.original_text, "")
                        self.assertNotEqual(op.candidate_text, "")

    def test_adjacent_ops_never_share_a_kind(self):
        for original, candidate in self.PAIRS:
            with self.subTest(original=original, candidate=candidate):
                row = kinds(word_diff(original, candidate))
                for left, right in zip(row, row[1:]):
                    self.assertNotEqual(left, right)

    def test_empty_ops_only_for_an_identical_empty_pair(self):
        self.assertEqual(word_diff("", ""), ())
        self.assertTrue(word_diff("", "x"))
        self.assertTrue(word_diff("x", ""))


class ProposalDiffsTest(unittest.TestCase):
    def test_one_diff_per_candidate_in_order(self):
        original = "The cat sat."
        candidates = ("The dog sat.", "The cat sat.", "A cat sat down.")
        diffs = proposal_diffs(original, candidates)
        self.assertIsInstance(diffs, tuple)
        self.assertEqual(len(diffs), len(candidates))
        for diff, candidate in zip(diffs, candidates):
            self.assertEqual(diff, word_diff(original, candidate))
        self.assertEqual(diffs[1], (DiffOp("equal", original, original),))

    def test_no_candidates_gives_empty_tuple(self):
        self.assertEqual(proposal_diffs("The cat sat.", ()), ())
        self.assertEqual(proposal_diffs("The cat sat.", []), ())

    def test_accepts_the_proposal_candidate_shape(self):
        # generation.propose.Proposal.candidates is a tuple[str, ...].
        candidates = tuple(["one two", "one three"])
        self.assertIsInstance(candidates, tuple)
        diffs = proposal_diffs("one two", candidates)
        self.assertEqual(len(diffs), 2)
        self.assertEqual(diffs[0], (DiffOp("equal", "one two", "one two"),))


if __name__ == "__main__":
    unittest.main()

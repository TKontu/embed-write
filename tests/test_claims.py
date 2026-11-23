"""Synthetic, offline checks for SP-01 claim selection."""

import unittest
from dataclasses import FrozenInstanceError

from analysis.claims import Claim, DEFAULT_CLAIM_MOVES, LabelledSentence, select_claims


def sentence(node_id="a", move="conclusion", confidence=0.8, level="sentence"):
    return LabelledSentence(node_id, level, move, confidence)


class ClaimSelectionTests(unittest.TestCase):
    def test_default_moves_and_exact_matching(self):
        self.assertEqual(DEFAULT_CLAIM_MOVES, frozenset({"conclusion", "interpretation"}))
        rows = [sentence(str(i), move) for i, move in enumerate(
            ["observation", "conclusion", "interpretation", "Conclusion", "conclusion "])]
        self.assertEqual(select_claims(rows), [
            Claim("1", "sentence", "conclusion", 0.8),
            Claim("2", "sentence", "interpretation", 0.8)])

    def test_custom_moves(self):
        self.assertEqual(select_claims([sentence(move="evidence"), sentence("b")],
                                      claim_moves={"evidence"}),
                         [Claim("a", "sentence", "evidence", 0.8)])

    def test_confidence_boundary_and_order(self):
        rows = [sentence("z", confidence=0.5), sentence("b", confidence=0.49),
                sentence("a", confidence=1)]
        self.assertEqual([c.node_id for c in select_claims(rows, min_confidence=0.5)],
                         ["z", "a"])
        self.assertEqual(len(select_claims([sentence(confidence=0)])), 1)

    def test_generator_is_consumed_once(self):
        class Once:
            def __init__(self):
                self.used = False

            def __iter__(self):
                if self.used:
                    raise AssertionError("input iterated twice")
                self.used = True
                yield sentence("b")
                yield sentence("a")

        self.assertEqual([c.node_id for c in select_claims(Once())], ["b", "a"])
        self.assertEqual(len(select_claims(sentence(str(i)) for i in range(3))), 3)

    def test_empty_input(self):
        self.assertEqual(select_claims(iter(())), [])

    def test_duplicate_ids_even_when_filtered(self):
        for rows in ([sentence(), sentence()],
                     [sentence(move="observation"), sentence(confidence=0)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                select_claims(rows, min_confidence=0.5)

    def test_mixed_levels_even_when_filtered(self):
        with self.assertRaises(ValueError):
            select_claims([sentence(move="observation"), sentence("b", level="paragraph")])

    def test_bad_text_fields(self):
        for field in ("node_id", "level", "move"):
            for value in ("", None, 1):
                args = dict(node_id="a", level="sentence", move="conclusion", confidence=0.8)
                args[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    LabelledSentence(**args)

    def test_bad_confidence(self):
        for value in (-0.1, 1.1, float("nan"), float("inf"), -float("inf"), None, "0.5", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sentence(confidence=value)

    def test_bad_min_confidence_even_on_empty_input(self):
        for value in (-0.1, 1.1, float("nan"), float("inf"), None, "0.5", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_claims([], min_confidence=value)

    def test_bad_claim_moves_even_on_empty_input(self):
        for moves in (set(), frozenset(), {""}, {1}, {"conclusion", None},
                      ["conclusion"], "conclusion", None, {"conclusion": True}):
            with self.subTest(moves=moves), self.assertRaises(ValueError):
                select_claims([], claim_moves=moves)

    def test_records_are_frozen(self):
        for record in (sentence(), Claim("a", "sentence", "conclusion", 0.8)):
            with self.assertRaises(FrozenInstanceError):
                record.confidence = 0.1


if __name__ == "__main__":
    unittest.main()

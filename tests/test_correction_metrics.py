import unittest

from service.correction_metrics import DraftCorrection, MoveCorrection, correction_metrics
from service.draft_assembly import DraftBlock


def _b(move, text):
    return DraftBlock(section="S", move=move, text=text, provenance="machine")


class CorrectionMetricsTest(unittest.TestCase):
    def test_unchanged_blocks(self):
        blocks = [_b("context", "The cat sat. The dog ran."), _b("aim", "We test it.")]
        r = correction_metrics(blocks, [b.text for b in blocks])
        self.assertIsInstance(r, DraftCorrection)
        self.assertEqual((r.machine_sentences, r.edited_sentences, r.share_edited), (3, 0, 0.0))

    def test_one_of_two_rewritten(self):
        r = correction_metrics([_b("context", "The cat sat. The dog ran.")], ["The cat sat. A dog walked."])
        self.assertEqual(r.by_move, (MoveCorrection("context", 2, 1, 0.5),))
        self.assertEqual(r.share_edited, 0.5)

    def test_same_move_aggregates_in_first_appearance_order(self):
        blocks = [_b("result", "One here."), _b("context", "Two here."), _b("result", "Three here. Four here.")]
        finals = ["One here.", "Changed.", "Three here. Four changed."]
        r = correction_metrics(blocks, finals)
        self.assertEqual(
            r.by_move,
            (MoveCorrection("result", 3, 1, 1 / 3), MoveCorrection("context", 1, 1, 1.0)),
        )
        self.assertEqual((r.machine_sentences, r.edited_sentences), (4, 2))
        self.assertEqual(r.share_edited, 0.5)

    def test_deleted_block_all_edited(self):
        r = correction_metrics([_b("aim", "First one. Second one.")], ["   \n"])
        self.assertEqual(r.by_move, (MoveCorrection("aim", 2, 2, 1.0),))

    def test_whitespace_not_edit_and_duplicates_multiset(self):
        r = correction_metrics([_b("aim", "The  cat\tsat.  Yes it did. ")], ["The cat sat.   Yes   it did."])
        self.assertEqual(r.edited_sentences, 0)
        r = correction_metrics([_b("aim", "Same line. Same line.")], ["Same line."])
        self.assertEqual((r.machine_sentences, r.edited_sentences), (2, 1))

    def test_empty_and_length_mismatch(self):
        r = correction_metrics([], [])
        self.assertEqual((r.by_move, r.machine_sentences, r.share_edited), ((), 0, 0.0))
        with self.assertRaises(ValueError):
            correction_metrics([_b("aim", "A.")], [])


if __name__ == "__main__":
    unittest.main()

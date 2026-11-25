import unittest

from service.grounding_check import (
    GeneratedSentence,
    GroundingReport,
    check_grounding,
    sentences_from_text,
)
from service.source_items import Provenance, SourceItem


def item(item_id):
    return SourceItem(
        id=item_id,
        type="note",
        content="Synthetic content.",
        units=(),
        provenance=Provenance(source="synthetic", locator=None, recorded_by="test", recorded_at=None),
    )


ITEMS = [item("s1"), item("s2")]


class GroundingCheckTest(unittest.TestCase):
    def test_unsupported_sentence_flagged_unlinked_and_kept(self):
        report = check_grounding(
            [
                GeneratedSentence("Alpha holds.", ("s1",)),
                GeneratedSentence("Beta is invented.", ()),
                GeneratedSentence("Gamma holds.", ("s2",)),
            ],
            ITEMS,
        )
        self.assertIsInstance(report, GroundingReport)
        self.assertEqual(len(report.sentences), 3)
        row = report.sentences[1]
        self.assertEqual((row.index, row.text), (1, "Beta is invented."))
        self.assertTrue(row.flagged)
        self.assertEqual(row.reason, "unlinked")
        self.assertFalse(report.sentences[0].flagged)
        self.assertIsNone(report.sentences[0].reason)

    def test_only_unknown_id_flagged_unknown_source(self):
        row = check_grounding([GeneratedSentence("A.", ("nope", "nope"))], ITEMS).sentences[0]
        self.assertTrue(row.flagged)
        self.assertEqual(row.reason, "unknown-source")
        self.assertEqual(row.unknown_ids, ("nope",))
        self.assertEqual(row.linked_ids, ())

    def test_mixed_ids_not_flagged_but_unknown_listed(self):
        row = check_grounding([GeneratedSentence("A.", ("x", "s2", "s1", "s2"))], ITEMS).sentences[0]
        self.assertFalse(row.flagged)
        self.assertIsNone(row.reason)
        self.assertEqual(row.linked_ids, ("s2", "s1"))
        self.assertEqual(row.unknown_ids, ("x",))

    def test_non_claim_never_flagged(self):
        row = check_grounding(
            [GeneratedSentence("In short.", ())], ITEMS, is_claim=lambda text: False
        ).sentences[0]
        self.assertFalse(row.flagged)
        self.assertIsNone(row.reason)

    def test_order_and_flagged_count(self):
        texts = ["One.", "Two.", "Three.", "Four."]
        ids = [(), ("s1",), ("zz",), ()]
        report = check_grounding(
            [GeneratedSentence(t, i) for t, i in zip(texts, ids)], ITEMS
        )
        self.assertEqual([r.text for r in report.sentences], texts)
        self.assertEqual([r.index for r in report.sentences], [0, 1, 2, 3])
        self.assertEqual(report.flagged_count, len(report.flagged))
        self.assertEqual([r.index for r in report.flagged], [0, 2, 3])

    def test_type_and_value_errors(self):
        with self.assertRaises(TypeError):
            check_grounding(["plain string"], ITEMS)
        with self.assertRaises(ValueError):
            check_grounding([GeneratedSentence("   ", ("s1",))], ITEMS)
        with self.assertRaises(ValueError):
            check_grounding([GeneratedSentence("", ())], ITEMS)

    def test_generators_consumed_once(self):
        consumed = []

        def items_gen():
            for it in ITEMS:
                consumed.append(it.id)
                yield it

        sentences = (GeneratedSentence(t, ("s2",)) for t in ["A.", "B."])
        report = check_grounding(sentences, items_gen())
        self.assertEqual(consumed, ["s1", "s2"])
        self.assertEqual(report.flagged_count, 0)
        self.assertEqual(len(report.sentences), 2)

    def test_sentences_from_text(self):
        rows = sentences_from_text("The sky is blue. Grass is green.", ["s1", "s2"])
        self.assertEqual(
            rows,
            (
                GeneratedSentence("The sky is blue.", ("s1", "s2")),
                GeneratedSentence("Grass is green.", ("s1", "s2")),
            ),
        )


if __name__ == "__main__":
    unittest.main()

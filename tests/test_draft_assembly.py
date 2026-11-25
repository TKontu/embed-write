import unittest
from pathlib import Path

from service.draft_assembly import AssembledDraft, DraftBlock, assemble_draft
from service.number_check import QuantityCheck
from service.source_items import Provenance, SourceItem

_PROV = Provenance(source="test", locator=None, recorded_by="t", recorded_at=None)


def _item(item_id, content, units=()):
    return SourceItem(id=item_id, type="note", content=content, units=tuple(units), provenance=_PROV)


SECTIONS = [
    ("Intro", [("context", "  First para.  "), ("aim", "Second para.")]),
    ("Method", [("setup", "Load was 12 kg."), ("result", "Mass rose by 7 kg.")]),
]


class AssembleDraftTest(unittest.TestCase):
    def test_markdown_and_blocks(self):
        d = assemble_draft(SECTIONS)
        self.assertIsInstance(d, AssembledDraft)
        self.assertEqual(
            d.markdown,
            "## Intro\n\nFirst para.\n\nSecond para.\n\n## Method\n\nLoad was 12 kg.\n\nMass rose by 7 kg.\n",
        )
        self.assertEqual(
            d.blocks,
            (
                DraftBlock("Intro", "context", "First para.", "machine"),
                DraftBlock("Intro", "aim", "Second para.", "machine"),
                DraftBlock("Method", "setup", "Load was 12 kg.", "machine"),
                DraftBlock("Method", "result", "Mass rose by 7 kg.", "machine"),
            ),
        )

    def test_status_draft(self):
        self.assertEqual(assemble_draft(SECTIONS).status, "draft")

    def test_module_never_mentions_reviewed(self):
        src = (Path(__file__).resolve().parents[1] / "service" / "draft_assembly.py").read_text()
        self.assertNotIn("reviewed", src)

    def test_value_errors(self):
        cases = [
            [("  ", [("m", "t")])],
            [("H", [("m", "   ")])],
            [("H", [("m", "")])],
            [("H", [("m", "text\n# Heading")])],
            [("H", [("m", "# Heading")])],
            [("A\n# B", [("m", "t")])],
            [("H", [])],
        ]
        for sections in cases:
            with self.subTest(sections=sections):
                with self.assertRaises(ValueError):
                    assemble_draft(sections)

    def test_quantity_checks_with_items(self):
        d = assemble_draft(SECTIONS, items=[_item("s1", "The load was 12 kg.")])
        self.assertEqual(len(d.quantity_checks), 4)
        self.assertTrue(all(isinstance(q, QuantityCheck) for q in d.quantity_checks))
        self.assertTrue(d.quantity_checks[2].all_matched)
        unmatched = d.quantity_checks[3].unmatched
        self.assertEqual(len(unmatched), 1)
        self.assertEqual((unmatched[0].value, unmatched[0].unit), (7.0, "kg"))

    def test_items_none(self):
        self.assertIsNone(assemble_draft(SECTIONS).quantity_checks)


if __name__ == "__main__":
    unittest.main()

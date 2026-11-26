"""CO-07: boilerplate and near-duplicate detection (LLM-built synthetic fixtures, offline)."""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from experiments import boilerplate as bp

DISCLAIMER = "This report is confidential and intended only for the named recipient."
SIDE_NOTE = "Prepared with assistance from the regional office staff."

BODIES = [
    "The river bank erosion near the old mill has accelerated after the spring floods and "
    "the footbridge foundations now show visible cracks along the eastern pillar.",
    "Quarterly sales of winter equipment rose sharply in the northern districts while the "
    "southern shops reported flat demand for skis and snowshoes throughout the season.",
    "A new reading programme for primary schools pairs older pupils with younger ones twice "
    "a week and teachers note improved vocabulary after the first two months of trials.",
    "The municipal bus timetable changes in autumn will reduce evening departures on two "
    "suburban lines and add an express connection between the hospital and the station.",
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.corpus = self.root / "corpus"
        self.corpus.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, files):
        for rel, text in files.items():
            path = self.corpus / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return self.corpus

    def flags(self, kind, **kw):
        return [f for f in bp.build_report(self.corpus, **kw)["flags"] if f["kind"] == kind]


class RepeatedTest(Base):
    def test_disclaimer_in_three_of_four_flagged_two_doc_passage_not(self):
        files = {}
        for i, body in enumerate(BODIES):
            parts = [f"# Report {i}", body]
            if i < 3:
                parts.append(DISCLAIMER)
            if i < 2:
                parts.append(SIDE_NOTE)
            files[f"d{i}.md"] = "\n\n".join(parts) + "\n"
        self.write(files)
        rep = self.flags("repeated", min_docs=3)
        texts = [f["text"] for f in rep]
        self.assertIn(bp.normalize(DISCLAIMER), texts)
        self.assertNotIn(bp.normalize(SIDE_NOTE), texts)
        flag = rep[texts.index(bp.normalize(DISCLAIMER))]
        self.assertEqual(flag["documents"], ["d0", "d1", "d2"])
        self.assertEqual(flag["count"], 3)

    def test_digit_variation_still_matches(self):
        self.write({
            f"d{i}.md": f"{body}\n\nPage {i + 1} of 1{i} - printed 2024-0{i + 1}-1{i}\n"
            for i, body in enumerate(BODIES[:3])
        })
        rep = self.flags("repeated")
        self.assertEqual(len(rep), 1)
        self.assertEqual(rep[0]["text"], "page # of # - printed #-#-#")
        self.assertEqual(rep[0]["count"], 3)


class NearDuplicateTest(Base):
    def test_near_identical_pair_flagged_unrelated_not(self):
        long_text = " ".join(BODIES) + " " + " ".join(BODIES[::-1])
        variant = long_text.replace("cracks", "fractures", 1)
        self.write({
            "a.md": long_text + "\n",
            "b.md": variant + "\n",
            "c.md": "Completely different content about bird migration over the coastal "
                    "marshes in late summer and the counting methods used by volunteers.\n",
            "d.md": "Notes on sourdough baking: hydration levels, starter feeding schedules "
                    "and oven temperatures for a crisp crust and an open crumb.\n",
        })
        nd = self.flags("near_duplicate_docs")
        self.assertEqual([f["documents"] for f in nd], [["a", "b"]])
        self.assertGreaterEqual(nd[0]["similarity"], 0.8)
        self.assertEqual(nd[0]["count"], 2)


class OutputTest(Base):
    def test_deterministic_bytes(self):
        self.write({f"d{i}.md": f"{b}\n\n{DISCLAIMER}\n" for i, b in enumerate(BODIES)})
        out1, out2 = self.root / "1.json", self.root / "2.json"
        self.assertEqual(bp.main(["report", str(self.corpus), str(out1)]), 0)
        self.assertEqual(bp.main(["report", str(self.corpus), str(out2)]), 0)
        self.assertEqual(out1.read_bytes(), out2.read_bytes())

    def test_existing_out_refused_without_force(self):
        self.write({"a.md": "x\n"})
        out = self.root / "o.json"
        out.write_text("keep", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(bp.main(["report", str(self.corpus), str(out)]), 1)
        self.assertEqual(out.read_text(encoding="utf-8"), "keep")
        self.assertEqual(bp.main(["report", str(self.corpus), str(out), "--force"]), 0)
        self.assertNotEqual(out.read_text(encoding="utf-8"), "keep")

    def test_empty_corpus_empty_report(self):
        rep = bp.build_report(self.corpus)
        self.assertEqual(rep["flags"], [])
        self.assertEqual(rep["totals"]["documents"], 0)
        self.assertEqual(rep["totals"]["flags"], 0)


class ResidualsTest(Base):
    def test_same_stem_in_subdirs_distinct(self):
        self.write({"a/x.md": f"{BODIES[0]}\n", "b/x.md": f"{BODIES[1]}\n"})
        rep = bp.build_report(self.corpus)
        self.assertEqual(rep["totals"]["documents"], 2)

    def test_same_stem_ids_in_flags(self):
        self.write({f"{d}/x.md": f"{b}\n\n{DISCLAIMER}\n"
                    for d, b in zip("abc", BODIES)})
        rep = self.flags("repeated")
        self.assertEqual(rep[0]["documents"], ["a/x", "b/x", "c/x"])

    def test_short_heading_min_words(self):
        self.write({f"d{i}.md": f"Executive Summary\n\n{b}\n" for i, b in enumerate(BODIES[:3])})
        texts = [f["text"] for f in self.flags("repeated")]
        self.assertNotIn("executive summary", texts)
        texts = [f["text"] for f in self.flags("repeated", min_words=1)]
        self.assertIn("executive summary", texts)
        rep = bp.build_report(self.corpus)
        self.assertEqual(rep["params"]["min_words"], 4)

    def test_min_words_cli(self):
        self.write({f"d{i}.md": f"Executive Summary\n\n{b}\n" for i, b in enumerate(BODIES[:3])})
        out = self.root / "o.json"
        self.assertEqual(bp.main(["report", str(self.corpus), str(out), "--min-words", "1"]), 0)
        self.assertIn("executive summary", out.read_text(encoding="utf-8"))

    def test_max_passages_caps_table(self):
        self.write({f"d{i}.md": f"{DISCLAIMER}\n\n{b}\n" for i, b in enumerate(BODIES)})
        full = bp.build_report(self.corpus)
        self.assertFalse(full["totals"]["passage_table_capped"])
        self.assertGreater(full["totals"]["distinct_passages"], 2)
        capped = bp.build_report(self.corpus, max_passages=2)
        self.assertTrue(capped["totals"]["passage_table_capped"])
        self.assertEqual(capped["totals"]["distinct_passages"], 2)
        self.assertEqual(capped["params"]["max_passages"], 2)
        # existing entries keep counting after the cap
        rep = [f for f in capped["flags"] if f["kind"] == "repeated"]
        self.assertEqual(rep[0]["text"], bp.normalize(DISCLAIMER))
        self.assertEqual(rep[0]["count"], 4)
        self.assertEqual(capped, bp.build_report(self.corpus, max_passages=2))

    def test_max_passages_cli(self):
        self.write({f"d{i}.md": f"{DISCLAIMER}\n\n{b}\n" for i, b in enumerate(BODIES)})
        out = self.root / "o.json"
        self.assertEqual(bp.main(["report", str(self.corpus), str(out), "--max-passages", "1"]), 0)
        self.assertIn('"passage_table_capped": true', out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

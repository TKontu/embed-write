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

    def test_min_words_counts_word_tokens_only(self):
        punct = "- - - | | Note"
        finnish = "- Ääni ja öljy | yö -"
        self.write({f"d{i}.md": f"{punct}\n\n{finnish}\n\n{b}\n"
                    for i, b in enumerate(BODIES[:3])})
        texts = [f["text"] for f in self.flags("repeated")]
        self.assertNotIn(bp.normalize(punct), texts)
        self.assertIn(bp.normalize(finnish), texts)

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


class ReviewTest(Base):
    """CO-07 review listing (LLM-built synthetic fixtures)."""

    def report_file(self, report, name="r.json"):
        import json
        path = self.root / name
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def review(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(err):
            code = bp.main(["review", *map(str, argv)])
        return code, out.getvalue(), err.getvalue()

    def sample(self):
        files = {f"d{i}.md": f"{BODIES[i]}\n\n{DISCLAIMER}\n" for i in range(3)}
        files["e.md"] = BODIES[0] + "\n"
        self.write(files)
        report = bp.build_report(self.corpus, min_docs=3, threshold=0.5)
        report["flags"].append({"kind": "near_duplicate_docs", "documents": ["z", "y"],
                                "count": 2, "similarity": 0.9375})
        return report

    def test_lists_repeated_and_near_duplicate(self):
        path = self.report_file(self.sample())
        code, out, err = self.review(path)
        self.assertEqual(code, 0, err)
        self.assertIn("flag", out.splitlines()[0].lower())
        self.assertIn(bp.normalize(DISCLAIMER), out)
        self.assertRegex(out, r"\[\d\] repeated  count: 3")
        self.assertIn("near_duplicate_docs", out)
        self.assertIn("similarity: 0.9375", out)
        self.assertIn("documents: y, z", out)
        self.assertIn("documents: d0, d1, d2", out)
        self.assertNotIn("capped", out)
        self.assertEqual(self.review(path)[1], out)

    def test_capped_line(self):
        report = self.sample()
        report["totals"]["passage_table_capped"] = True
        code, out, _ = self.review(self.report_file(report))
        self.assertEqual(code, 0)
        self.assertIn("passage table capped", out)

    def test_limit_omits(self):
        report = self.sample()
        n = len(report["flags"])
        self.assertGreaterEqual(n, 2)
        code, out, _ = self.review(self.report_file(report), "--limit", "1")
        self.assertEqual(code, 0)
        self.assertIn("[1]", out)
        self.assertNotIn("[2]", out)
        self.assertIn(f"{n - 1} more flag(s) omitted", out)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bp.main(["review", str(self.report_file(report)), "--limit", "0"])

    def test_bad_input_exit_2(self):
        bad_json = self.root / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        wrong = self.report_file({"flags": "nope"}, "wrong.json")
        wrong2 = self.report_file({"flags": [{"kind": "repeated"}], "totals": {}}, "w2.json")
        for path in (self.root / "missing.json", bad_json, wrong, wrong2, self.root):
            code, out, err = self.review(path)
            self.assertEqual(code, 2, path)
            self.assertIn(str(path), err)
            self.assertNotIn("Traceback", err)
            self.assertEqual(len(err.strip().splitlines()), 1)

    def test_boolean_count_or_similarity_rejected(self):
        rep = {"kind": "repeated", "documents": ["a"], "count": 3, "text": "t"}
        near = {"kind": "near_duplicate_docs", "documents": ["a", "b"], "count": 2,
                "similarity": 0.9}
        cases = [dict(rep, count=True), dict(near, count=False),
                 dict(near, similarity=True), dict(near, similarity=False)]
        for i, flag in enumerate(cases):
            path = self.report_file({"flags": [flag], "totals": {}}, f"b{i}.json")
            with self.assertRaises(bp.ReportError, msg=flag):
                bp.load_report(path)
            code, _, err = self.review(path)
            self.assertEqual(code, 2, flag)
            self.assertNotIn("Traceback", err)

    def test_deeply_nested_json_report_error(self):
        path = self.root / "deep.json"
        path.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
        with self.assertRaises(bp.ReportError):
            bp.load_report(path)
        code, out, err = self.review(path)
        self.assertEqual(code, 2)
        self.assertIn(str(path), err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

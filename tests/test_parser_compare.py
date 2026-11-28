"""D-016 check tool tests. Fixtures are LLM-built synthetic text, built in-test; no network."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from experiments import parser_compare as pc

SENTINEL = "zebracornflower"

DOC_A_PYPDF = f"""# Intro {SENTINEL}

one two three

## Method

four five
"""

DOC_A_MINERU = f"""# Intro {SENTINEL}

one two three

## Method

| a | b |
| --- | --- |
| 1 | 2 |

$$
x = y
$$

text after

| c |
| --- |
"""


def _write_run(root: Path, files: list[dict]) -> Path:
    out = root
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for f in files:
        e = {"source": f"/private/{f['name']}.pdf", "format": "pdf", "output": None,
             "status": f["status"], "headings": None, "roundtrip": None}
        if f.get("md") is not None:
            p = out / f"{f['name']}.md"
            p.write_text(f["md"], encoding="utf-8")
            e["output"] = str(p)
        if f["status"] == "failed":
            e["error"] = f"ValueError: secret {SENTINEL} text"
        e.update(f.get("extra", {}))
        entries.append(e)
    (out / "ingest_report.json").write_text(json.dumps({"files": entries}), encoding="utf-8")
    return out


class CountTests(unittest.TestCase):
    def test_counts(self):
        c = pc.count_markdown(io.StringIO(DOC_A_MINERU))
        self.assertEqual(c, {"headings": 2, "tables": 2, "formulas": 1,
                             "words": pc.count_markdown(io.StringIO(DOC_A_MINERU))["words"]})
        self.assertEqual(c["words"], len(DOC_A_MINERU.split()))

    def test_fenced_heading_not_counted(self):
        c = pc.count_markdown(io.StringIO("```\n# no\n```\n# yes\n"))
        self.assertEqual(c["headings"], 1)

    def test_inline_display_formula(self):
        c = pc.count_markdown(io.StringIO("$$ a = b $$\n\n$$\nc\n$$\n"))
        self.assertEqual(c["formulas"], 2)


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        names = ["Beta Report", "Alpha Paper", "Gamma Scan"]
        self.names = names
        self.py = _write_run(self.tmp / "py", [
            {"name": "Beta Report", "status": "ok", "md": DOC_A_PYPDF},
            {"name": "Alpha Paper", "status": "ok", "md": "hello world\n"},
            {"name": "Gamma Scan", "status": "failed"},
        ])
        self.mu = _write_run(self.tmp / "mu", [
            {"name": "Beta Report", "status": "ok", "md": DOC_A_MINERU,
             "extra": {"parser": "mineru", "dropped": {"page_number": 3, "footer": 1}}},
            {"name": "Alpha Paper", "status": "ok", "md": "hello world\n",
             "extra": {"parser": "pypdf", "mineru_error": "TimeoutError"}},
            {"name": "Gamma Scan", "status": "ok", "md": "ocr words here\n",
             "extra": {"parser": "mineru", "dropped": {"page_number": 2}}},
        ])
        self.report = pc.compare(self.py, self.mu)

    def test_opaque_indices_sorted_by_name(self):
        docs = self.report["documents"]
        self.assertEqual([d["doc"] for d in docs], ["doc-01", "doc-02", "doc-03"])
        # sorted order: Alpha, Beta, Gamma
        self.assertEqual(docs[0]["pypdf"]["words"], 2)
        self.assertEqual(docs[1]["mineru"]["tables"], 2)

    def test_failed_side_handled(self):
        gamma = self.report["documents"][2]
        self.assertEqual(gamma["pypdf"]["status"], "failed")
        self.assertEqual(gamma["pypdf"]["error_type"], "ValueError")
        self.assertIsNone(gamma["pypdf"]["words"])
        self.assertEqual(gamma["mineru"]["status"], "ok")
        self.assertEqual(gamma["mineru"]["words"], 3)

    def test_parser_and_dropped(self):
        t = self.report["totals"]
        self.assertEqual(t["mineru"]["parser"], {"mineru": 2, "pypdf": 1})
        self.assertEqual(t["mineru"]["fallback_errors"], {"TimeoutError": 1})
        self.assertEqual(t["mineru"]["dropped"], {"footer": 1, "page_number": 5})
        self.assertEqual(t["pypdf"]["ok"], 2)
        self.assertEqual(t["pypdf"]["failed"], 1)
        self.assertEqual(t["mineru"]["ok"], 3)
        self.assertEqual(t["mineru"]["headings"], 2)
        self.assertEqual(t["mineru"]["formulas"], 1)
        self.assertEqual(t["pypdf"]["headings"], 2)

    def test_no_text_or_names(self):
        blob = json.dumps(self.report)
        self.assertNotIn(SENTINEL, blob)
        for n in self.names + ["Alpha", "Beta", "Gamma", "private"]:
            self.assertNotIn(n, blob)
        for w in ("hello", "ocr", "Intro", "Method"):
            self.assertNotIn(w, blob)

    def test_cli_writes_report(self):
        out = self.tmp / "r.json"
        with redirect_stdout(io.StringIO()) as buf:
            rc = pc.main(["compare", str(self.py), str(self.mu), str(out)])
        self.assertEqual(rc, 0)
        data = json.loads(out.read_text())
        self.assertEqual(len(data["documents"]), 3)
        self.assertNotIn(SENTINEL, buf.getvalue())

    def test_cli_refuses_overwrite(self):
        out = self.tmp / "r.json"
        out.write_text("{}")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(pc.main(["compare", str(self.py), str(self.mu), str(out)]), 2)


if __name__ == "__main__":
    unittest.main()

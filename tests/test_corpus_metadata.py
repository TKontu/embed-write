"""CO-06: per-report metadata schema validation (synthetic fixtures only, offline)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import corpus_metadata as cm
from experiments.corpus import iter_documents

MISSING = object()

VALID = {
    "doc_id": "r-001",
    "genre": "inspection-report",
    "date": "2024-03-15",
    "author_role": "inspector",
    "language": "fi",
    "length": 1200,
}


def rec(**over):
    r = dict(VALID)
    for k, v in over.items():
        if v is MISSING:
            r.pop(k)
        else:
            r[k] = v
    return r


class RecordTests(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(cm.validate_record(VALID), [])

    def test_date_forms(self):
        for d in ("2024", "2024-03", "2024-03-15"):
            self.assertEqual(cm.validate_record(rec(date=d)), [], d)
        for d in ("2024-13", "2024-02-30", "24-03-15", "2024/03/15", "2024-3-5", 2024):
            self.assertTrue(cm.validate_record(rec(date=d)), d)

    def test_language_tags(self):
        for t in ("fi", "en", "en-GB", "sv-FI", "zh-Hant"):
            self.assertEqual(cm.validate_record(rec(language=t)), [], t)
        for t in ("", "english", "e", "en_GB", "en-", "EN-gb-"):
            self.assertTrue(cm.validate_record(rec(language=t)), t)

    def test_missing_field(self):
        errs = cm.validate_record(rec(genre=MISSING))
        self.assertTrue(any("missing" in e and "genre" in e for e in errs))

    def test_unknown_field(self):
        errs = cm.validate_record(rec(colour="red"))
        self.assertTrue(any("unknown" in e and "colour" in e for e in errs))

    def test_wrong_type(self):
        self.assertTrue(cm.validate_record(rec(length="1200")))
        self.assertTrue(cm.validate_record(rec(length=True)))
        self.assertTrue(cm.validate_record(rec(length=1.5)))
        self.assertTrue(cm.validate_record(rec(author_role=3)))
        self.assertTrue(cm.validate_record(rec(doc_id="")))
        self.assertTrue(cm.validate_record([1, 2]))

    def test_negative_length(self):
        errs = cm.validate_record(rec(length=-1))
        self.assertTrue(any("length" in e for e in errs))
        self.assertEqual(cm.validate_record(rec(length=0)), [])

    def test_genre_check(self):
        self.assertEqual(cm.validate_record(VALID, genre="inspection-report"), [])
        self.assertTrue(cm.validate_record(VALID, genre="memo"))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, lines):
        p = self.dir / "meta.jsonl"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def test_valid_file(self):
        p = self.write([json.dumps(VALID), "", json.dumps(rec(doc_id="r-002"))])
        self.assertEqual(cm.validate_file(p), [])
        self.assertEqual([r["doc_id"] for r in cm.iter_records(p)], ["r-001", "r-002"])

    def test_line_numbered_errors(self):
        p = self.write([
            json.dumps(VALID),                              # 1 ok
            json.dumps(rec(doc_id="r-002", genre=MISSING)),  # 2 missing
            json.dumps(rec(doc_id="r-003", extra=1)),       # 3 unknown
            json.dumps(rec(doc_id="r-004", length="x")),    # 4 type
            json.dumps(rec(doc_id="r-005", date="2024-99")),  # 5 date
            json.dumps(rec(doc_id="r-006", language="xx_YY")),  # 6 lang
            json.dumps(rec(doc_id="r-007", length=-5)),     # 7 negative
            json.dumps(VALID),                              # 8 duplicate
            '{"doc_id": "r-009", "genre"',                  # 9 torn
            json.dumps(rec(doc_id="r-010", genre="memo")),  # 10 genre mismatch
        ])
        errs = cm.validate_file(p, genre="inspection-report")
        lines = sorted({e.line for e in errs})
        self.assertEqual(lines, list(range(2, 11)))
        by = {e.line: e.message for e in errs}
        self.assertIn("duplicate", by[8])
        self.assertIn("JSON", by[9])
        self.assertIn("genre", by[10])
        self.assertTrue(str(errs[0]).startswith(f"{p}:{errs[0].line}:"))

    def test_iter_records_raises(self):
        p = self.write([json.dumps(VALID), "not json"])
        it = cm.iter_records(p)
        self.assertEqual(next(it)["doc_id"], "r-001")
        with self.assertRaises(cm.MetadataError) as ctx:
            next(it)
        self.assertEqual(ctx.exception.line, 2)

    def test_streams_line_by_line(self):
        p = self.write([json.dumps(VALID), "garbage"])
        it = cm.iter_records(p)
        # first record arrives before the bad line is parsed
        self.assertEqual(next(it)["doc_id"], "r-001")

    def test_word_count_with_iter_documents(self):
        docs = self.dir / "docs"
        docs.mkdir()
        (docs / "a.md").write_text("# Title\n\none two  three\tfour\n", encoding="utf-8")
        (doc,) = list(iter_documents(docs))
        self.assertEqual(cm.word_count(doc.text), 6)
        self.assertEqual(cm.word_count(""), 0)

    def test_cli_exit_codes(self):
        good = self.write([json.dumps(VALID)])
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(cm.main(["validate", str(good)]), 0)
            self.assertEqual(cm.main(["validate", str(good), "--genre", "memo"]), 1)
        bad = self.dir / "bad.jsonl"
        bad.write_text(json.dumps(VALID) + "\n{\n", encoding="utf-8")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(cm.main(["validate", str(bad)]), 1)
        self.assertIn(":2:", err.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(cm.main(["validate", str(self.dir / "nope.jsonl")]), 0)


if __name__ == "__main__":
    unittest.main()

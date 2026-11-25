"""CO-05: conversion-quality checks over a CO-04 ingest report (synthetic fixtures only)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import conversion_quality as cq


def words(n: int) -> str:
    """n words on short wrapped lines, so only the flag under test can fire."""
    lines = []
    while n > 0:
        lines.append(" ".join(["word"] * min(10, n)))
        n -= min(10, n)
    return "\n".join(lines)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.outdir = self.root / "md"
        self.outdir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, name: str, text: str) -> str:
        path = self.outdir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def entry(self, source="a.docx", output=None, status="ok", headings=1,
              roundtrip=None, error=None):
        item = {"source": source, "output": output, "format": "docx",
                "status": status, "headings": headings, "roundtrip": roundtrip}
        if error is not None:
            item["error"] = error
        return item

    def report(self, *entries) -> dict:
        return {"files": list(entries), "summary": {"ok": len(entries)}}

    def codes(self, result) -> list[str]:
        return [f["code"] for f in result["flags"]]


class HeadingFlagTests(Base):
    def test_no_headings_fires_above_200_words(self):
        out = self.doc("a.md", words(250))
        result = cq.check_entry(self.entry(output=out, headings=0))
        self.assertIn("no_headings", self.codes(result))

    def test_no_headings_silent_at_200_words(self):
        out = self.doc("a.md", words(200))
        result = cq.check_entry(self.entry(output=out, headings=0))
        self.assertEqual(self.codes(result), [])

    def test_no_headings_uses_counted_headings_when_missing(self):
        out = self.doc("a.md", "# Title\n\n" + words(250))
        result = cq.check_entry(self.entry(output=out, headings=None))
        self.assertEqual(self.codes(result), [])

    def test_few_headings_fires_below_one_per_1500_words(self):
        out = self.doc("a.md", "# Title\n\n" + words(1600))
        result = cq.check_entry(self.entry(output=out, headings=1))
        self.assertIn("few_headings", self.codes(result))

    def test_few_headings_silent_at_1500_words(self):
        # "# Title" adds two words, so 1498 body words make exactly 1500.
        out = self.doc("a.md", "# Title\n\n" + words(1498))
        result = cq.check_entry(self.entry(output=out, headings=1))
        self.assertEqual(self.codes(result), [])

    def test_few_headings_silent_with_enough_headings(self):
        out = self.doc("a.md", "# A\n\n# B\n\n# C\n\n" + words(3000))
        result = cq.check_entry(self.entry(output=out, headings=3))
        self.assertEqual(self.codes(result), [])


class RoundtripFlagTests(Base):
    def test_error_string_fires(self):
        out = self.doc("a.md", "# H\n\ntext.\n")
        result = cq.check_entry(self.entry(output=out, roundtrip="error: node failed"))
        self.assertIn("roundtrip_failed", self.codes(result))
        self.assertIn("node failed", result["flags"][0]["detail"])

    def test_failed_dict_fires(self):
        out = self.doc("a.md", "# H\n\ntext.\n")
        rt = {"parses": False, "roundtrip_idempotent": False, "section_count": 0}
        result = cq.check_entry(self.entry(output=out, roundtrip=rt))
        self.assertIn("roundtrip_failed", self.codes(result))

    def test_non_idempotent_dict_fires(self):
        out = self.doc("a.md", "# H\n\ntext.\n")
        rt = {"parses": True, "roundtrip_idempotent": False, "section_count": 1}
        result = cq.check_entry(self.entry(output=out, roundtrip=rt))
        self.assertIn("roundtrip_failed", self.codes(result))

    def test_skip_and_success_stay_silent(self):
        out = self.doc("a.md", "# H\n\ntext.\n")
        for rt in ("skipped: node unavailable", "ok",
                   {"parses": True, "roundtrip_idempotent": True, "section_count": 1}, None):
            with self.subTest(roundtrip=rt):
                result = cq.check_entry(self.entry(output=out, roundtrip=rt))
                self.assertEqual(self.codes(result), [])


class StatusFlagTests(Base):
    def test_conversion_failed_carries_error(self):
        result = cq.check_entry(self.entry(output=None, status="failed", headings=None,
                                           error="ValueError: encrypted"))
        self.assertEqual(self.codes(result), ["conversion_failed"])
        self.assertEqual(result["flags"][0]["detail"], "ValueError: encrypted")
        self.assertIsNone(result["flags"][0]["line"])

    def test_unsupported_is_not_flagged(self):
        result = cq.check_entry(self.entry(output=None, status="unsupported", headings=None))
        self.assertEqual(result["flags"], [])

    def test_missing_output_file(self):
        result = cq.check_entry(self.entry(output=str(self.outdir / "gone.md")))
        self.assertEqual(self.codes(result), ["missing_output"])

    def test_empty_output(self):
        out = self.doc("a.md", "  \n\n\t\n")
        result = cq.check_entry(self.entry(output=out, headings=0))
        self.assertEqual(self.codes(result), ["empty_output"])


class TableFlagTests(Base):
    def test_clean_table_is_silent(self):
        out = self.doc("a.md", "# H\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertNotIn("broken_table", self.codes(cq.check_entry(self.entry(output=out))))

    def test_cell_count_mismatch_reports_line(self):
        out = self.doc("a.md", "# H\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 |\n")
        result = cq.check_entry(self.entry(output=out))
        table = [f for f in result["flags"] if f["code"] == "broken_table"]
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["line"], 6)

    def test_table_without_separator_reports_header_line(self):
        out = self.doc("a.md", "# H\n\n| A | B |\n| 1 | 2 |\n")
        result = cq.check_entry(self.entry(output=out))
        table = [f for f in result["flags"] if f["code"] == "broken_table"]
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["line"], 3)

    def test_two_clean_tables_are_silent(self):
        out = self.doc("a.md", "# H\n\n| A |\n| --- |\n| 1 |\n\ntext\n\n"
                                "| B | C |\n| --- | --- |\n| 2 | 3 |\n")
        self.assertNotIn("broken_table", self.codes(cq.check_entry(self.entry(output=out))))

    def test_pipe_prose_is_not_a_table(self):
        out = self.doc("a.md", "# H\n\nUse a | b for alternatives.\n")
        self.assertNotIn("broken_table", self.codes(cq.check_entry(self.entry(output=out))))


class TextFlagTests(Base):
    def test_merged_columns_fires_on_three_space_runs(self):
        out = self.doc("a.md", "# H\n\nalpha    beta    gamma    delta\n")
        flags = [f for f in cq.check_entry(self.entry(output=out))["flags"]
                 if f["code"] == "merged_columns"]
        self.assertEqual([f["line"] for f in flags], [3])

    def test_two_space_runs_stay_silent(self):
        out = self.doc("a.md", "# H\n\nalpha    beta    gamma\n")
        self.assertNotIn("merged_columns", self.codes(cq.check_entry(self.entry(output=out))))

    def test_long_line_fires_above_2000_characters(self):
        out = self.doc("a.md", "# H\n\n" + "x" * 2001 + "\n")
        flags = [f for f in cq.check_entry(self.entry(output=out))["flags"]
                 if f["code"] == "long_line"]
        self.assertEqual([f["line"] for f in flags], [3])

    def test_long_line_silent_at_2000_characters(self):
        out = self.doc("a.md", "# H\n\n" + "x" * 2000 + "\n")
        self.assertNotIn("long_line", self.codes(cq.check_entry(self.entry(output=out))))

    def test_fenced_code_is_ignored(self):
        body = "\n".join([
            "# H", "", "text.", "",
            "```", "| A | B |", "| --- |", "| 1 |", "x" * 2500,
            "a    b    c    d", "```", "",
        ])
        out = self.doc("a.md", body)
        self.assertEqual(self.codes(cq.check_entry(self.entry(output=out))), [])

    def test_tilde_fence_is_ignored(self):
        out = self.doc("a.md", "# H\n\n~~~\na    b    c    d\n~~~\n")
        self.assertEqual(self.codes(cq.check_entry(self.entry(output=out))), [])


class ReportTests(Base):
    def test_clean_report_has_no_flagged_documents(self):
        out = self.doc("a.md", "# H\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        report = self.report(self.entry(output=out))
        result = cq.build_report(report)
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["summary"]["documents_checked"], 1)
        self.assertEqual(result["summary"]["documents_flagged"], 0)
        self.assertEqual(result["summary"]["flags"], {})

    def test_documents_sorted_by_source_and_counts_summarised(self):
        good = self.doc("good.md", "# H\n\ntext.\n")
        bad = self.doc("bad.md", words(250))
        report = self.report(
            self.entry(source="z.docx", output=bad, headings=0),
            self.entry(source="a.docx", output=good),
            self.entry(source="m.docx", output=bad, headings=0),
        )
        result = cq.build_report(report)
        self.assertEqual([d["source"] for d in result["documents"]],
                         ["m.docx", "z.docx"])
        self.assertEqual(result["summary"]["documents_checked"], 3)
        self.assertEqual(result["summary"]["documents_flagged"], 2)
        self.assertEqual(result["summary"]["flags"], {"no_headings": 2})
        self.assertEqual(result["documents"][0]["output"], bad)

    def test_flags_are_sorted_and_deterministic(self):
        out = self.doc("a.md", words(250) + "\n| A |\n| --- |\n| 1 | 2 |\n")
        first = cq.build_report(self.report(self.entry(output=out, headings=0)))
        second = cq.build_report(self.report(self.entry(output=out, headings=0)))
        self.assertEqual(json.dumps(first), json.dumps(second))
        flags = first["documents"][0]["flags"]
        self.assertEqual([(f["line"] or 0, f["code"]) for f in flags],
                         sorted((f["line"] or 0, f["code"]) for f in flags))

    def test_output_quotes_no_document_text(self):
        marker = "SECRETMARKER"
        out = self.doc("a.md", "# H\n\n" + marker * 200 + "\n")
        result = cq.build_report(self.report(self.entry(output=out)))
        self.assertEqual(len(result["documents"]), 1)
        self.assertNotIn(marker, json.dumps(result))
        for flag in result["documents"][0]["flags"]:
            self.assertLessEqual(len(flag["detail"]), 120)

    def test_many_lines_processed(self):
        body = "# H\n\n" + "\n".join(["a short line."] * 400) + "\n"
        out = self.doc("a.md", body)
        result = cq.check_entry(self.entry(output=out))
        self.assertEqual(result["flags"], [])


class CliTests(Base):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cq.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def report_file(self, *entries) -> Path:
        path = self.root / "ingest_report.json"
        path.write_text(json.dumps(self.report(*entries)), encoding="utf-8")
        return path

    def test_check_writes_json_and_exits_zero(self):
        out = self.doc("a.md", "# H\n\ntext.\n")
        path = self.report_file(self.entry(output=out))
        target = self.root / "quality.json"
        code, _, err = self.run_cli("check", path, target)
        self.assertEqual(code, 0, err)
        result = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(result["summary"]["documents_checked"], 1)
        self.assertNotIn("files", result)

    def test_existing_output_refused_without_force_then_overwritten(self):
        out = self.doc("a.md", "# H\n\ntext.\n")
        path = self.report_file(self.entry(output=out))
        target = self.root / "quality.json"
        target.write_text("stale", encoding="utf-8")
        code, _, err = self.run_cli("check", path, target)
        self.assertEqual(code, 2)
        self.assertIn("exists", err)
        self.assertEqual(target.read_text(encoding="utf-8"), "stale")
        code, _, err = self.run_cli("check", path, target, "--force")
        self.assertEqual(code, 0, err)
        self.assertIn("documents", json.loads(target.read_text(encoding="utf-8")))

    def test_missing_report_is_a_usage_error(self):
        code, _, err = self.run_cli("check", self.root / "absent.json", self.root / "out.json")
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_invalid_report_is_a_usage_error(self):
        path = self.root / "bad.json"
        path.write_text(json.dumps({"summary": {}}), encoding="utf-8")
        code, _, err = self.run_cli("check", path, self.root / "out.json")
        self.assertEqual(code, 2)
        self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()

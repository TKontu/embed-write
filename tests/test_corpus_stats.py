"""CO-09: corpus statistics report (synthetic fixtures only, offline)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import corpus_stats as cs


def rec(doc_id, genre):
    return {
        "doc_id": doc_id,
        "genre": genre,
        "date": "2024-03-15",
        "author_role": "inspector",
        "language": "fi",
        "length": 10,
    }


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

    def metadata(self, records):
        path = self.root / "meta.jsonl"
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
        )
        return path


class HeadingTests(Base):
    def test_usage_counts_and_levels(self):
        self.write({
            "a.md": "# Title\n\ntext.\n\n## Method\n\nbody.\n",
            "b.md": "  ##   METHOD  ##\n\nbody.\n\n### Method\n\nmore.\n",
            "c.md": "# Other\n",
        })
        report = cs.build_report(self.corpus)
        self.assertEqual(report["documents"], 3)
        self.assertEqual(report["headings"]["title"], {"documents": 1, "levels": [1]})
        # Same heading text normalised (spaces, case, closing #s); one doc counts once.
        self.assertEqual(report["headings"]["method"], {"documents": 2, "levels": [2, 3]})
        self.assertEqual(report["headings"]["other"], {"documents": 1, "levels": [1]})

    def test_empty_heading_and_non_headings(self):
        self.write({
            "a.md": "#not a heading\ntext\n####### seven\n##\nbody\n#Closed#\nx\n",
        })
        report = cs.build_report(self.corpus)
        # "#x" and "####### x" have no space after the #s; "#Closed#" is not ATX either.
        self.assertEqual(
            report["headings"],
            {"": {"documents": 1, "levels": [2]}},
        )


class FenceTests(Base):
    def headings(self, text):
        self.write({"a.md": text})
        return cs.build_report(self.corpus)["headings"]

    def test_backtick_fence_hides_heading(self):
        h = self.headings("# Real\n\n```python\n# not a heading\n```\n\n## After\n")
        self.assertEqual(sorted(h), ["after", "real"])

    def test_tilde_fence_hides_heading(self):
        h = self.headings("# Real\n   ~~~~\n# not a heading\n~~~~~\n## After\n")
        self.assertEqual(sorted(h), ["after", "real"])

    def test_shorter_or_other_marker_does_not_close(self):
        h = self.headings(
            "# Real\n````\n```\n~~~~\n# not a heading\n````\n## After\n"
        )
        self.assertEqual(sorted(h), ["after", "real"])

    def test_four_space_indent_does_not_open(self):
        h = self.headings("# Real\n    ```\n## After\n")
        self.assertEqual(sorted(h), ["after", "real"])

    def test_unclosed_fence_runs_to_eof(self):
        self.write({"a.md": "# Real\n```\n# not a heading\nbody.\n"})
        report = cs.build_report(self.corpus)
        self.assertEqual(sorted(report["headings"]), ["real"])


class SectionStatsTests(Base):
    def test_preamble_section(self):
        self.write({
            "a.md": "One two three. Four five six.\n\n# H\n\nSeven eight.\n",
        })
        report = cs.build_report(self.corpus)
        self.assertEqual(report["sections"]["count"], 2)
        self.assertEqual(
            report["sections"]["words"],
            {"min": 2, "median": 4.0, "max": 6, "total": 8},
        )
        self.assertEqual(
            report["sections"]["sentences"],
            {"min": 1, "median": 1.5, "max": 2, "total": 3},
        )
        self.assertEqual(report["per_document"]["a.md"], {"sections": 2, "sentences": 3})

    def test_lengths_across_sections(self):
        self.write({
            "a.md": "# A\none.\n\n# B\none two.\n\n# C\none two three.\n",
        })
        report = cs.build_report(self.corpus)
        self.assertEqual(report["sections"]["count"], 3)
        self.assertEqual(
            report["sections"]["words"],
            {"min": 1, "median": 2.0, "max": 3, "total": 6},
        )
        self.assertEqual(
            report["sections"]["sentences"],
            {"min": 1, "median": 1.0, "max": 1, "total": 3},
        )

    def test_empty_corpus(self):
        report = cs.build_report(self.corpus)
        self.assertEqual(report["documents"], 0)
        self.assertEqual(report["headings"], {})
        self.assertEqual(report["per_document"], {})
        self.assertEqual(report["sections"]["count"], 0)
        self.assertEqual(
            report["sections"]["words"],
            {"min": 0, "median": 0.0, "max": 0, "total": 0},
        )

    def test_paths_are_posix_and_no_body_text(self):
        self.write({
            "sub/dir/a.md": "SECRETBODYTEXT one. Two.\n",
            "b.md": "# T\nSECRETBODYTEXT\n",
        })
        report = cs.build_report(self.corpus)
        self.assertEqual(sorted(report["per_document"]), ["b.md", "sub/dir/a.md"])
        self.assertEqual(
            report["per_document"]["sub/dir/a.md"], {"sections": 1, "sentences": 2}
        )
        self.assertNotIn("SECRETBODYTEXT", json.dumps(report))

    def test_uses_real_sentence_segmentation(self):
        # A naive split on "." would count three sentences.
        self.write({"a.md": "# A\nDr. Smith went home. It rained.\n"})
        report = cs.build_report(self.corpus)
        self.assertEqual(report["per_document"]["a.md"]["sentences"], 2)


class OutputTests(Base):
    def test_deterministic_sorted_output(self):
        self.write({
            "b.md": "# Beta\nTwo.\n",
            "a.md": "# Alpha\nOne.\n",
        })
        one = cs.build_report(self.corpus)
        two = cs.build_report(self.corpus)
        self.assertEqual(json.dumps(one, sort_keys=True), json.dumps(two, sort_keys=True))
        out1, out2 = self.root / "1.json", self.root / "2.json"
        cs.write_report(one, out1)
        cs.write_report(two, out2)
        self.assertEqual(out1.read_text(encoding="utf-8"), out2.read_text(encoding="utf-8"))
        text = out1.read_text(encoding="utf-8")
        self.assertEqual(
            text,
            json.dumps(one, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        self.assertEqual(
            list(json.loads(text)),
            ["documents", "headings", "per_document", "sections"],
        )

    def test_write_refuses_overwrite(self):
        self.write({"a.md": "# A\nOne.\n"})
        report = cs.build_report(self.corpus)
        out = self.root / "stats.json"
        cs.write_report(report, out)
        with self.assertRaises(FileExistsError):
            cs.write_report(report, out)
        cs.write_report(report, out, force=True)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), report)


class MetadataTests(Base):
    def test_genre_join_and_unmatched_counts(self):
        # Join is by path stem: sub/b.md matches doc_id "b".
        self.write({
            "a.md": "# A\none.\n",
            "sub/b.md": "# B\ntwo.\n",
            "c.md": "# C\nthree.\n",
        })
        meta = self.metadata([rec("a", "report"), rec("b", "report"), rec("zz", "memo")])
        report = cs.build_report(self.corpus, metadata=meta)
        self.assertEqual(
            report["metadata"],
            {
                "genres": {"report": 2},
                "matched_documents": 2,
                "unmatched_documents": 1,
                "unmatched_records": 1,
            },
        )

    def test_no_metadata_key_without_option(self):
        self.write({"a.md": "# A\n"})
        self.assertNotIn("metadata", cs.build_report(self.corpus))


class CliTests(Base):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cs.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_report_writes_and_refuses_overwrite(self):
        self.write({"a.md": "# A\none. Two.\n"})
        out = self.root / "stats.json"
        self.assertEqual(self.run_cli("report", self.corpus, out)[0], 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["documents"], 1)
        self.assertEqual(report["sections"]["count"], 1)
        code, _, err = self.run_cli("report", self.corpus, out)
        self.assertEqual(code, 1)
        self.assertIn("exists", err)
        self.assertEqual(self.run_cli("report", self.corpus, out, "--force")[0], 0)

    def test_missing_corpus_dir(self):
        out = self.root / "out.json"
        code, _, err = self.run_cli("report", self.root / "nope", out)
        self.assertNotEqual(code, 0)
        self.assertIn("not found", err)
        self.assertFalse(out.exists())

    def test_metadata_option(self):
        self.write({"a.md": "# A\n"})
        meta = self.metadata([rec("a", "report")])
        out = self.root / "stats.json"
        self.assertEqual(self.run_cli("report", self.corpus, out, "--metadata", meta)[0], 0)
        self.assertEqual(
            json.loads(out.read_text(encoding="utf-8"))["metadata"]["genres"],
            {"report": 1},
        )

    def test_invalid_metadata_exit_1(self):
        self.write({"a.md": "# A\n"})
        bad = self.root / "bad.jsonl"
        bad.write_text('{"doc_id": "a"}\n', encoding="utf-8")
        out = self.root / "stats.json"
        code, _, err = self.run_cli("report", self.corpus, out, "--metadata", bad)
        self.assertEqual(code, 1)
        self.assertIn("error", err)
        self.assertFalse(out.exists())


class ClosingSequenceTests(unittest.TestCase):
    def test_commonmark_closing_sequence(self):
        for line, want in (("### ###", ""), ("#", ""), ("# foo#", "foo#"), ("## Title ##", "title")):
            m = cs._ATX.match(line)
            self.assertEqual(cs._heading_text(m.group(2)), want, line)


if __name__ == "__main__":
    unittest.main()

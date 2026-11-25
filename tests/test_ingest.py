"""CO-04 ingestion tests. Fixtures are synthetic and built in-test."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import ingest

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text, style=None, bold=False, italic=False, numbered=False):
    ppr = ""
    inner = ""
    if style:
        inner += f'<w:pStyle w:val="{style}"/>'
    if numbered:
        inner += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    if inner:
        ppr = f"<w:pPr>{inner}</w:pPr>"
    rpr = ""
    if bold or italic:
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + "</w:rPr>"
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _mixed_p():
    return ('<w:p><w:r><w:t xml:space="preserve">Plain </w:t></w:r>'
            '<w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>'
            '<w:r><w:t xml:space="preserve"> and </w:t></w:r>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r>'
            '<w:r><w:t>.</w:t></w:r></w:p>')


def _cell(t):
    return f"<w:tc>{_p(t)}</w:tc>"


def make_docx(path: Path) -> None:
    body = (_p("Title", style="Heading1") + _mixed_p() + _p("Sub", style="Heading2")
            + _p("one", style="ListParagraph") + _p("two", numbered=True)
            + "<w:tbl><w:tr>" + _cell("A") + _cell("B") + "</w:tr><w:tr>"
            + _cell("1") + _cell("2") + "</w:tr></w:tbl>")
    doc = f'<?xml version="1.0"?><w:document {W}><w:body>{body}<w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)


EXPECTED = ("# Title\n\nPlain **bold** and *italic*.\n\n## Sub\n\n- one\n- two\n\n"
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n")

HTML = ("<html><head><title>x</title><style>p{}</style></head><body>"
        "<h1>Title</h1><p>Plain <strong>bold</strong> and <em>italic</em>.</p>"
        "<h2>Sub</h2><ul><li>one</li><li>two</li></ul>"
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        "</body></html>")


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = self.tmp / "src"
        self.out = self.tmp / "out"
        self.src.mkdir()

    def run_cli(self, *extra, check=False):
        argv = ["convert", str(self.src), str(self.out), *extra]
        if not check:
            argv.append("--no-check")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = ingest.main(argv)
        return code, err.getvalue()

    def report(self):
        data = json.loads((self.out / "ingest_report.json").read_text())
        return {Path(f["source"]).name: f for f in data["files"]}

    def test_docx_converts(self):
        make_docx(self.src / "r.docx")
        self.assertEqual(ingest.convert_docx(self.src / "r.docx"), EXPECTED)

    def test_html_converts(self):
        self.assertEqual(ingest.convert_html(HTML), EXPECTED)

    def test_html_ordered_list(self):
        self.assertEqual(ingest.convert_html("<ol><li>a</li><li>b</li></ol>"), "1. a\n2. b\n")

    def test_txt_and_md(self):
        (self.src / "a.txt").write_text("first line\nsame para\n\n\nsecond\n")
        (self.src / "b.md").write_text("# Kept\n\nas is\n")
        code, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual((self.out / "a.md").read_text(), "first line\nsame para\n\nsecond\n")
        self.assertEqual((self.out / "b.md").read_text(), "# Kept\n\nas is\n")
        rep = self.report()
        self.assertEqual(rep["a.txt"]["status"], "ok")
        self.assertEqual(rep["b.md"]["headings"], 1)
        self.assertEqual(rep["b.md"]["format"], "md")

    def test_unsupported_and_corrupt(self):
        (self.src / "p.pdf").write_bytes(b"%PDF-1.4")
        (self.src / "x.xyz").write_text("?")
        (self.src / "bad.docx").write_bytes(b"not a zip")
        make_docx(self.src / "good.docx")
        code, _ = self.run_cli()
        self.assertEqual(code, 1)
        rep = self.report()
        self.assertEqual(rep["p.pdf"]["status"], "unsupported")
        self.assertEqual(rep["p.pdf"]["reason"], "pdf: dependency decision pending")
        self.assertEqual(rep["x.xyz"]["status"], "unsupported")
        self.assertEqual(rep["bad.docx"]["status"], "failed")
        self.assertTrue(rep["bad.docx"]["error"])
        self.assertIsNone(rep["bad.docx"]["output"])
        self.assertEqual(rep["good.docx"]["status"], "ok")
        self.assertEqual(rep["good.docx"]["headings"], 2)
        self.assertEqual((self.out / "good.md").read_text(), EXPECTED)

    def test_refuses_existing_output_without_force(self):
        (self.src / "a.txt").write_text("hi\n")
        self.assertEqual(self.run_cli()[0], 0)
        code, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        self.assertEqual(self.run_cli("--force")[0], 0)

    def test_stem_collision_fails_second(self):
        (self.src / "a.txt").write_text("t\n")
        (self.src / "a.html").write_text("<p>h</p>")
        self.run_cli()
        statuses = sorted(f["status"] for f in self.report().values())
        self.assertEqual(statuses, ["failed", "ok"])

    @unittest.skipUnless(ingest.node_available(), "node unavailable")
    def test_roundtrip_check(self):
        make_docx(self.src / "r.docx")
        code, _ = self.run_cli(check=True)
        self.assertEqual(code, 0)
        rt = self.report()["r.docx"]["roundtrip"]
        self.assertEqual(rt, {"parses": True, "roundtrip_idempotent": True, "section_count": 2})

    def test_roundtrip_skipped_without_node(self):
        (self.src / "a.txt").write_text("hi\n")
        orig = ingest.node_available
        ingest.node_available = lambda: False
        self.addCleanup(setattr, ingest, "node_available", orig)
        self.run_cli(check=True)
        self.assertEqual(self.report()["a.txt"]["roundtrip"], "skipped: node unavailable")

    def test_batches_of_50(self):
        calls = []
        orig = ingest._run_node
        ingest._run_node = lambda paths: calls.append(len(paths)) or [
            {"path": p, "parses": True, "roundtrip_idempotent": True, "section_count": 0}
            for p in paths]
        self.addCleanup(setattr, ingest, "_run_node", orig)
        res = ingest.check_roundtrip([f"/x/{i}.md" for i in range(120)])
        self.assertEqual(calls, [50, 50, 20])
        self.assertEqual(len(res), 120)


if __name__ == "__main__":
    unittest.main()

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


def _np(text, num_id, ilvl=0):
    return (f'<w:p><w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/>'
            f'</w:numPr></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>')


def make_numbered_docx(path: Path, body: str, numbering: str | None) -> None:
    """Synthetic LLM-built DOCX with optional word/numbering.xml."""
    doc = f'<?xml version="1.0"?><w:document {W}><w:body>{body}<w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)
        if numbering is not None:
            z.writestr("word/numbering.xml", numbering)


def numbering_xml(fmts: dict[int, list[str]]) -> str:
    """fmts: numId -> numFmt per ilvl (abstractNumId = numId + 10)."""
    parts = []
    for num_id, levels in fmts.items():
        lvls = "".join(f'<w:lvl w:ilvl="{i}"><w:numFmt w:val="{f}"/></w:lvl>'
                       for i, f in enumerate(levels))
        parts.append(f'<w:abstractNum w:abstractNumId="{num_id + 10}">{lvls}</w:abstractNum>')
    for num_id in fmts:
        parts.append(f'<w:num w:numId="{num_id}"><w:abstractNumId w:val="{num_id + 10}"/></w:num>')
    return f'<?xml version="1.0"?><w:numbering {W}>{"".join(parts)}</w:numbering>'


EXPECTED = ("# Title\n\nPlain **bold** and *italic*.\n\n## Sub\n\n- one\n- two\n\n"
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n")

HTML = ("<html><head><title>x</title><style>p{}</style></head><body>"
        "<h1>Title</h1><p>Plain <strong>bold</strong> and <em>italic</em>.</p>"
        "<h2>Sub</h2><ul><li>one</li><li>two</li></ul>"
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        "</body></html>")


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """Minimal valid PDF (synthetic, LLM-built): one Helvetica text stream per page."""
    n = len(pages)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
            + f"] /Count {n} >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, lines in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>")
        ops = "BT /F1 12 Tf 14 TL 72 720 Td " + " ".join(
            f"({_pdf_escape(t)}) Tj T*" for t in lines) + " ET" if lines else ""
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


PDF_SKIP = "pypdf not installed"


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
        (self.src / "x.xyz").write_text("?")
        (self.src / "bad.docx").write_bytes(b"not a zip")
        make_docx(self.src / "good.docx")
        code, _ = self.run_cli()
        self.assertEqual(code, 1)
        rep = self.report()
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

    @unittest.skipIf(ingest.roundtrip_unavailable_reason(), ingest.roundtrip_unavailable_reason())
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

    def test_roundtrip_skipped_without_docmodel_deps(self):
        (self.src / "a.txt").write_text("hi\n")
        orig_node, orig_deps = ingest.node_available, ingest.DOCMODEL_DEPS
        ingest.node_available = lambda: True
        ingest.DOCMODEL_DEPS = self.src / "no-such-node_modules"
        self.addCleanup(setattr, ingest, "node_available", orig_node)
        self.addCleanup(setattr, ingest, "DOCMODEL_DEPS", orig_deps)
        self.run_cli(check=True)
        self.assertEqual(self.report()["a.txt"]["roundtrip"],
                         "skipped: docmodel dependencies not installed")

    @unittest.skipUnless(ingest.HAVE_PYPDF, PDF_SKIP)
    def test_pdf_two_pages_heading(self):
        (self.src / "r.pdf").write_bytes(make_pdf([
            ["1. Introduction", "", "The first page has body text."],
            ["Second page body continues here."]]))
        md = ingest.convert_pdf(self.src / "r.pdf")
        self.assertIn("## 1. Introduction\n", md)
        self.assertIn("The first page has body text.", md)
        self.assertIn("Second page body continues here.", md)

    @unittest.skipUnless(ingest.HAVE_PYPDF, PDF_SKIP)
    def test_pdf_heading_levels_follow_numbering(self):
        (self.src / "r.pdf").write_bytes(make_pdf([
            ["1. Scope", "", "Body about scope.", "", "1.2 Details", "", "Detail body text."]]))
        md = ingest.convert_pdf(self.src / "r.pdf")
        self.assertIn("## 1. Scope\n", md)
        self.assertIn("### 1.2 Details\n", md)
        self.assertNotIn("# Body", md)

    @unittest.skipUnless(ingest.HAVE_PYPDF, PDF_SKIP)
    def test_pdf_page_numbers_and_hyphenation(self):
        (self.src / "r.pdf").write_bytes(make_pdf([
            ["This is an exam-", "ple of joining.", "", "3"], ["Next page.", "", "- 4 -"]]))
        md = ingest.convert_pdf(self.src / "r.pdf")
        self.assertIn("example of joining.", md)
        self.assertNotRegex(md, r"(?m)^\s*-?\s*[34]\s*-?\s*$")

    def test_pdf_heading_heuristic_on_text(self):
        md = ingest.pdf_text_to_markdown(["Overview\n\nSome body sentence here.\n\nEnd."])
        self.assertTrue(md.startswith("## Overview\n"))
        self.assertTrue(md.rstrip().endswith("End."))

    @unittest.skipUnless(ingest.HAVE_PYPDF, PDF_SKIP)
    def test_pdf_without_text_fails_with_ocr_reason(self):
        (self.src / "scan.pdf").write_bytes(make_pdf([[]]))
        self.run_cli()
        e = self.report()["scan.pdf"]
        self.assertEqual(e["status"], "failed")
        self.assertIn("no extractable text (OCR not supported)", e["error"])

    @unittest.skipUnless(ingest.HAVE_PYPDF, PDF_SKIP)
    def test_pdf_corrupt_isolated_and_ok_counted(self):
        (self.src / "bad.pdf").write_bytes(b"%PDF-1.4 garbage")
        (self.src / "good.pdf").write_bytes(make_pdf([["2. Results", "", "Results body."]]))
        (self.src / "a.txt").write_text("hi\n")
        code, _ = self.run_cli()
        self.assertEqual(code, 1)
        rep = self.report()
        self.assertEqual(rep["bad.pdf"]["status"], "failed")
        self.assertTrue(rep["bad.pdf"]["error"])
        self.assertEqual(rep["good.pdf"]["status"], "ok")
        self.assertEqual(rep["good.pdf"]["format"], "pdf")
        self.assertEqual(rep["good.pdf"]["headings"], 1)
        self.assertEqual(rep["a.txt"]["status"], "ok")

    def test_pdf_unsupported_without_pypdf(self):
        orig = ingest.HAVE_PYPDF
        ingest.HAVE_PYPDF = False
        self.addCleanup(setattr, ingest, "HAVE_PYPDF", orig)
        (self.src / "p.pdf").write_bytes(b"%PDF-1.4")
        self.run_cli()
        e = self.report()["p.pdf"]
        self.assertEqual((e["status"], e["reason"]), ("unsupported", "pypdf not installed"))

    @unittest.skipUnless(ingest.HAVE_PYPDF and not ingest.roundtrip_unavailable_reason(),
                         "pypdf or roundtrip check unavailable")
    def test_pdf_roundtrip_check(self):
        (self.src / "r.pdf").write_bytes(make_pdf([["1. Intro", "", "Body."], ["1.1 More", "", "Text."]]))
        code, _ = self.run_cli(check=True)
        self.assertEqual(code, 0)
        rt = self.report()["r.pdf"]["roundtrip"]
        self.assertTrue(rt["parses"] and rt["roundtrip_idempotent"])
        self.assertEqual(rt["section_count"], 2)

    def test_out_inside_src_not_rescanned(self):
        (self.src / "a.txt").write_text("hi\n")
        self.out = self.src / "out"
        self.run_cli()
        self.run_cli("--force")
        data = json.loads((self.out / "ingest_report.json").read_text())
        sources = [f["source"] for f in data["files"]]
        self.assertEqual([Path(s).name for s in sources], ["a.txt"])
        self.assertEqual(data["summary"], {"ok": 1, "failed": 0, "unsupported": 0})

    def test_docx_decimal_numbering_ordered(self):
        body = _np("a", 1) + _np("b", 1) + _p("break") + _np("c", 1) + _np("d", 2)
        make_numbered_docx(self.src / "n.docx", body, numbering_xml({1: ["decimal"], 2: ["bullet"]}))
        self.assertEqual(ingest.convert_docx(self.src / "n.docx"),
                         "1. a\n2. b\n\nbreak\n\n1. c\n- d\n")

    def test_docx_bullet_numbering_dash(self):
        make_numbered_docx(self.src / "b.docx", _np("a", 1) + _np("b", 1),
                           numbering_xml({1: ["bullet"]}))
        self.assertEqual(ingest.convert_docx(self.src / "b.docx"), "- a\n- b\n")

    def test_docx_missing_numbering_xml_dash(self):
        make_numbered_docx(self.src / "m.docx", _np("a", 1) + _np("b", 7), None)
        self.assertEqual(ingest.convert_docx(self.src / "m.docx"), "- a\n- b\n")

    def test_docx_nested_levels_indent(self):
        body = _np("a", 1) + _np("a1", 1, 1) + _np("a2", 1, 1) + _np("b", 1) + _np("b1", 1, 1)
        make_numbered_docx(self.src / "x.docx", body, numbering_xml({1: ["decimal", "lowerLetter"]}))
        self.assertEqual(ingest.convert_docx(self.src / "x.docx"),
                         "1. a\n   1. a1\n   2. a2\n2. b\n   1. b1\n")

    def _num_raw(self, abstract_lvls: str, num_extra: str = "") -> str:
        return (f'<?xml version="1.0"?><w:numbering {W}>'
                f'<w:abstractNum w:abstractNumId="11">{abstract_lvls}</w:abstractNum>'
                f'<w:num w:numId="1"><w:abstractNumId w:val="11"/>{num_extra}</w:num>'
                f'</w:numbering>')

    def test_docx_abstract_start_honoured(self):
        num = self._num_raw('<w:lvl w:ilvl="0"><w:start w:val="3"/><w:numFmt w:val="decimal"/></w:lvl>')
        make_numbered_docx(self.src / "s.docx", _np("a", 1) + _np("b", 1), num)
        self.assertEqual(ingest.convert_docx(self.src / "s.docx"), "3. a\n4. b\n")

    def test_docx_start_override_honoured(self):
        num = self._num_raw('<w:lvl w:ilvl="0"><w:start w:val="3"/><w:numFmt w:val="decimal"/></w:lvl>',
                            '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/></w:lvlOverride>')
        make_numbered_docx(self.src / "o.docx", _np("a", 1) + _np("b", 1), num)
        self.assertEqual(ingest.convert_docx(self.src / "o.docx"), "5. a\n6. b\n")

    def test_docx_lvl_override_fmt_and_start(self):
        num = self._num_raw('<w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl>',
                            '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:start w:val="7"/>'
                            '<w:numFmt w:val="upperRoman"/></w:lvl></w:lvlOverride>')
        make_numbered_docx(self.src / "v.docx", _np("a", 1) + _np("b", 1), num)
        self.assertEqual(ingest.convert_docx(self.src / "v.docx"), "7. a\n8. b\n")

    def test_docx_letter_formats_ordered(self):
        make_numbered_docx(self.src / "l.docx", _np("a", 1) + _np("b", 1),
                           numbering_xml({1: ["lowerLetter"]}))
        self.assertEqual(ingest.convert_docx(self.src / "l.docx"), "1. a\n2. b\n")

    def test_docx_empty_paragraph_keeps_counting(self):
        body = _np("a", 1) + _p("") + _np("b", 1) + _p("x") + _np("c", 1)
        make_numbered_docx(self.src / "e.docx", body, numbering_xml({1: ["decimal"]}))
        self.assertEqual(ingest.convert_docx(self.src / "e.docx"), "1. a\n2. b\n\nx\n\n1. c\n")

    def _styled_docx(self, name, body, numbering, styles):
        make_numbered_docx(self.src / name, body, numbering)
        with zipfile.ZipFile(self.src / name, "a") as z:
            if styles is not None:
                z.writestr("word/styles.xml", f'<?xml version="1.0"?><w:styles {W}>{styles}</w:styles>')
        return ingest.convert_docx(self.src / name)

    def test_docx_style_inherited_numbering(self):
        styles = ('<w:style w:styleId="NumBase"><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/>'
                  '</w:numPr></w:pPr></w:style>'
                  '<w:style w:styleId="Child"><w:basedOn w:val="NumBase"/></w:style>'
                  '<w:style w:styleId="LoopA"><w:basedOn w:val="LoopB"/></w:style>'
                  '<w:style w:styleId="LoopB"><w:basedOn w:val="LoopA"/></w:style>')
        body = _p("a", style="Child") + _p("b", style="Child") + _p("c", style="LoopA")
        out = self._styled_docx("st.docx", body, numbering_xml({1: ["decimal", "decimal"]}), styles)
        self.assertEqual(out, "   1. a\n   2. b\n\nc\n")

    def test_docx_style_numbering_missing_or_bad_styles(self):
        body = _p("a", style="Child") + _np("b", 1)
        num = numbering_xml({1: ["decimal"]})
        self.assertEqual(self._styled_docx("ms.docx", body, num, None), "a\n\n1. b\n")
        make_numbered_docx(self.src / "bad.docx", body, num)
        with zipfile.ZipFile(self.src / "bad.docx", "a") as z:
            z.writestr("word/styles.xml", "<not xml")
        self.assertEqual(ingest.convert_docx(self.src / "bad.docx"), "a\n\n1. b\n")

    def test_docx_num_style_link_resolved(self):
        num = (f'<?xml version="1.0"?><w:numbering {W}>'
               '<w:abstractNum w:abstractNumId="20"><w:numStyleLink w:val="ListNums"/></w:abstractNum>'
               '<w:abstractNum w:abstractNumId="21"><w:styleLink w:val="ListNums"/>'
               '<w:lvl w:ilvl="0"><w:start w:val="4"/><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>'
               '<w:abstractNum w:abstractNumId="22"><w:numStyleLink w:val="Cyc"/></w:abstractNum>'
               '<w:num w:numId="1"><w:abstractNumId w:val="20"/></w:num>'
               '<w:num w:numId="2"><w:abstractNumId w:val="21"/></w:num>'
               '<w:num w:numId="3"><w:abstractNumId w:val="22"/></w:num>'
               '</w:numbering>')
        styles = ('<w:style w:type="numbering" w:styleId="ListNums"><w:pPr><w:numPr>'
                  '<w:numId w:val="2"/></w:numPr></w:pPr></w:style>'
                  '<w:style w:type="numbering" w:styleId="Cyc"><w:pPr><w:numPr>'
                  '<w:numId w:val="3"/></w:numPr></w:pPr></w:style>')
        body = _np("a", 1) + _np("b", 1) + _p("x") + _np("c", 3)
        self.assertEqual(self._styled_docx("sl.docx", body, num, styles), "4. a\n5. b\n\nx\n\n- c\n")

    def test_docx_lvl_restart(self):
        num = self._num_raw('<w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>'
                            '<w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/><w:lvlRestart w:val="0"/></w:lvl>'
                            '<w:lvl w:ilvl="2"><w:numFmt w:val="decimal"/><w:lvlRestart w:val="1"/></w:lvl>')
        body = (_np("a", 1) + _np("a1", 1, 1) + _np("a1i", 1, 2) + _np("a2", 1, 1) + _np("a2i", 1, 2)
                + _np("b", 1) + _np("b1", 1, 1) + _np("b1i", 1, 2))
        make_numbered_docx(self.src / "r.docx", body, num)
        self.assertEqual(ingest.convert_docx(self.src / "r.docx"),
                         "1. a\n   1. a1\n      1. a1i\n   2. a2\n      2. a2i\n"
                         "2. b\n   3. b1\n      1. b1i\n")

    def test_docx_empty_numbered_paragraph_no_number(self):
        body = _np("a", 1) + _np("", 1) + _np("b", 1)
        make_numbered_docx(self.src / "en.docx", body, numbering_xml({1: ["decimal"]}))
        self.assertEqual(ingest.convert_docx(self.src / "en.docx"), "1. a\n2. b\n")

    @unittest.skipIf(ingest.roundtrip_unavailable_reason(), ingest.roundtrip_unavailable_reason())
    def test_numbered_docx_roundtrip(self):
        body = _p("T", style="Heading1") + _np("a", 1) + _np("a1", 1, 1) + _np("b", 1)
        make_numbered_docx(self.src / "n.docx", body, numbering_xml({1: ["decimal", "decimal"]}))
        code, _ = self.run_cli(check=True)
        self.assertEqual(code, 0)
        rt = self.report()["n.docx"]["roundtrip"]
        self.assertTrue(rt["parses"] and rt["roundtrip_idempotent"])

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

class MarkdownEscapeTest(unittest.TestCase):
    """R155/A1: source text never becomes Markdown syntax it was not."""

    def docx(self, body):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        doc = f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'
        with zipfile.ZipFile(d / "e.docx", "w") as z:
            z.writestr("word/document.xml", doc)
        return ingest.convert_docx(d / "e.docx")

    def test_docx_inline_specials_escaped_bold_kept(self):
        md = self.docx(_p("a*b*c_d") + _p("x", bold=True))
        self.assertEqual(md, "a\\*b\\*c\\_d\n\n**x**\n")

    def test_docx_line_start_heading_escaped(self):
        self.assertEqual(self.docx(_p("# not heading")), "\\# not heading\n")
        self.assertEqual(self.docx(_p("Real", style="Heading1")), "# Real\n")

    def test_txt_list_markers_escaped(self):
        md = ingest.convert_txt("1. not list\n\n- not bullet\n\n2) also\n+ plus\n---\n> q\n")
        self.assertEqual(md, "1\\. not list\n\n\\- not bullet\n\n"
                             "2\\) also\n\\+ plus\n\\---\n\\> q\n")

    def test_txt_backslash_and_code(self):
        self.assertEqual(ingest.convert_txt("a\\b `c` <d> [e]"),
                         "a\\\\b \\`c\\` \\<d\\> \\[e\\]\n")

    def test_html_text_escaped_real_bold_kept(self):
        md = ingest.convert_html("<p>[x](y) &lt;b&gt; <b>real</b></p><h2>T</h2><ul><li>i</li></ul>")
        self.assertEqual(md, "\\[x\\](y) \\<b\\> **real**\n\n## T\n\n- i\n")

    def test_html_line_start_escaped(self):
        self.assertEqual(ingest.convert_html("<p># no</p>"), "\\# no\n")

    def test_pdf_headings_kept_body_escaped(self):
        md = ingest.pdf_text_to_markdown(["1. Intro\nSome *body* text here.\n\n- dash para."])
        self.assertTrue(md.startswith("## 1. Intro\n"), md)
        self.assertIn("Some \\*body\\* text here.", md)
        self.assertIn("\\- dash para.", md)

    # R156/A1: entity refs, pipes, ~~~ fences, indented code, table-cell escapes.
    def test_entity_refs_escaped(self):
        self.assertEqual(self.docx(_p("a &amp;amp; b &amp;#123; &amp;#x1F; &amp; c")),
                         "a \\&amp; b \\&#123; \\&#x1F; & c\n")
        self.assertEqual(ingest.convert_txt("x &copy; &#9; y & z"), "x \\&copy; \\&#9; y & z\n")
        self.assertEqual(ingest.convert_html("<p>&amp;lt;b&amp;gt; &amp;#65; a &amp; b</p>"),
                         "\\&lt;b\\&gt; \\&#65; a & b\n")

    def test_pipes_escaped_outside_tables(self):
        self.assertEqual(self.docx(_p("a | b | c")), "a \\| b \\| c\n")
        self.assertEqual(ingest.convert_txt("| a | b |\n|---|---|"), "\\| a \\| b \\|\n\\|---\\|---\\|\n")
        self.assertEqual(ingest.convert_html("<p>a|b</p>"), "a\\|b\n")

    def test_table_cell_pipe_escaped_once(self):
        md = ingest.convert_html("<table><tr><td>a|b</td><td>c</td></tr></table>")
        self.assertEqual(md, "| a\\|b | c |\n| --- | --- |\n")
        md = self.docx("<w:tbl><w:tr>" + _cell("a|b") + _cell("c") + "</w:tr></w:tbl>")
        self.assertEqual(md, "| a\\|b | c |\n| --- | --- |\n")

    def test_tilde_fence_escaped(self):
        self.assertEqual(self.docx(_p("~~~ python")), "\\~~~ python\n")
        self.assertEqual(ingest.convert_txt("~~~\ncode\n~~~"), "\\~~~\ncode\n\\~~~\n")
        self.assertEqual(ingest.convert_txt("```x"), "\\`\\`\\`x\n")

    def test_indented_code_neutralised(self):
        self.assertEqual(ingest.convert_txt("    code line\n\tcode2"), "code line\ncode2\n")
        self.assertEqual(ingest.convert_txt("  two spaces"), "  two spaces\n")
        self.assertEqual(self.docx('<w:p><w:r><w:tab/><w:t xml:space="preserve">    x</w:t></w:r></w:p>'),
                         "x\n")

    def test_docx_table_cells_no_line_start_escapes(self):
        md = self.docx("<w:tbl><w:tr>" + _cell("# h") + _cell("- d") + _cell("1. n")
                       + "</w:tr></w:tbl>")
        self.assertEqual(md, "| # h | - d | 1. n |\n| --- | --- | --- |\n")

    def test_md_passthrough_unchanged(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        (d / "s").mkdir()
        (d / "s" / "b.md").write_text("# K\n\na*b*\n")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            ingest.main(["convert", str(d / "s"), str(d / "o"), "--no-check"])
        self.assertEqual((d / "o" / "b.md").read_text(), "# K\n\na*b*\n")


if __name__ == "__main__":
    unittest.main()

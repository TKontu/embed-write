"""CO-04: convert source documents to Markdown for the corpus (stdlib + pypdf).

Formats: .docx (zipfile + xml.etree: paragraphs, Heading1..6 -> ATX headings,
bold/italic runs, list paragraphs -> ``-`` items or, when word/numbering.xml gives
the numId/ilvl a decimal* numFmt, ``1.``/``2.`` items (counter per numId and level,
restarting after a non-list block); nested ilvl indents 3 spaces per level; simple
tables -> pipe tables),
.html/.htm (html.parser: h1-h6, p, ul/ol/li, table, strong/b, em/i), .txt
(blank-line separated paragraphs), .md (copied) and .pdf (pypdf text per page:
blank-line paragraphs, page-number-only lines dropped, hyphenated line breaks
joined, heuristic headings: a short line without terminal punctuation followed
by body text; numbering depth sets the level, ``1.`` -> ``##``, ``1.2`` ->
``###``, unnumbered ``##``). Encrypted/unreadable PDFs and PDFs without
extractable text (scans; no OCR) are ``failed``. Without pypdf, ``.pdf`` is
``unsupported`` ("pypdf not installed"); other extensions likewise unsupported.
Not handled: images, footnotes, tracked changes, nested tables, merged cells,
hyperlinks (text kept), numbering lvlOverride/start values (numbers start at 1),
non-decimal numbering formats (emitted as ``-``), PDF layout, tables and images.
Files under OUT_DIR are never scanned as input, even when OUT_DIR is inside SRC_DIR.

Files are processed one at a time. After conversion each output is checked by
docmodel/scripts/check-roundtrip.js (batches of at most 50 paths) when ``node``
is available; otherwise ``roundtrip`` is ``"skipped: node unavailable"``.

CLI: python -m experiments.ingest convert SRC_DIR OUT_DIR [--force] [--no-check]
Exit 0 when every supported file converted, 1 when any failed/unsupported,
2 on usage errors (including existing output without --force).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    from pypdf import PdfReader
    HAVE_PYPDF = True
except ImportError:  # pragma: no cover - exercised by monkeypatching HAVE_PYPDF
    PdfReader = None
    HAVE_PYPDF = False

REPO = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO / "docmodel" / "scripts" / "check-roundtrip.js"
REPORT_NAME = "ingest_report.json"
BATCH = 50
FORMATS = {".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html", ".txt": "txt", ".md": "md"}
PDF_REASON = "pypdf not installed"
OCR_REASON = "no extractable text (OCR not supported)"
_PAGENUM_RE = re.compile(r"^\s*(?:page\s+)?[-\u2013\u2014]?\s*\d{1,4}\s*[-\u2013\u2014]?"
                         r"(?:\s*(?:/|of)\s*\d{1,4})?\s*$", re.I)
_NUMBERED_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)(\.?)\s+\S")
WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_RE = re.compile(r"^#{1,6}(\s|$)")


_MD_INLINE_RE = re.compile(r"([\\`*_\[\]<>])")
_MD_ORDERED_RE = re.compile(r"(\d{1,9})([.)])(?=\s|$)")


def _md_escape_line_starts(text: str) -> str:
    """Backslash-escape block markers (#, >, -/+ bullets, 1./1) ordered, ===/--- rules)
    that open a line; inline specials are left to _md_escape."""
    out = []
    for line in text.split("\n"):
        rest = line.lstrip()
        lead = line[: len(line) - len(rest)]
        if rest[:1] in ("#", ">") or re.match(r"[-+](\s|$)", rest) \
                or re.fullmatch(r"(=+|-+)\s*", rest):
            rest = "\\" + rest
        else:
            m = _MD_ORDERED_RE.match(rest)
            if m:
                rest = m.group(1) + "\\" + rest[m.end(1):]
        out.append(lead + rest)
    return "\n".join(out)


def _md_escape(text: str, line_starts: bool = True) -> str:
    """Escape raw source text so CommonMark reads it literally. Apply before the converter
    adds its own markup; line_starts=False for fragments that do not open a line."""
    text = _MD_INLINE_RE.sub(r"\\\1", text)
    return _md_escape_line_starts(text) if line_starts else text


def _esc_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _table(rows: list[list[str]]) -> str:
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(_esc_cell(c) for c in rows[0]) + " |",
             "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(_esc_cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _join_blocks(blocks: list[tuple[str, str]]) -> str:
    """blocks: (kind, text). Consecutive list items are joined by single newlines."""
    out: list[str] = []
    prev = None
    for kind, text in blocks:
        if not text.strip():
            continue
        if out:
            out.append("\n" if kind == "li" and prev == "li" else "\n\n")
        out.append(text)
        prev = kind
    return "".join(out) + "\n" if out else ""


def _wrap(text: str, bold: bool, italic: bool) -> str:
    if not text.strip() or not (bold or italic):
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = text.strip()
    if bold:
        core = f"**{core}**"
    if italic:
        core = f"*{core}*"
    return lead + core + trail


def _on(el) -> bool:
    if el is None:
        return False
    return el.get(WNS + "val", "true") not in ("0", "false", "none")


def _docx_para_text(p) -> str:
    parts = []
    for r in p.iter(WNS + "r"):
        rpr = r.find(WNS + "rPr")
        bold = rpr is not None and _on(rpr.find(WNS + "b"))
        italic = rpr is not None and _on(rpr.find(WNS + "i"))
        text = ""
        for child in r:
            if child.tag == WNS + "t":
                text += child.text or ""
            elif child.tag == WNS + "tab":
                text += " "
            elif child.tag in (WNS + "br", WNS + "cr"):
                text += " "
        parts.append(_wrap(_md_escape(text, line_starts=False), bold, italic))
    return _md_escape_line_starts("".join(parts).replace("****", "").strip())


def _lvl_props(lvl, base: tuple[str, int] = ("", 1)) -> tuple[str, int]:
    """(numFmt, start) of a <w:lvl>, inheriting missing values from base."""
    fmt, start = base
    f, st = lvl.find(WNS + "numFmt"), lvl.find(WNS + "start")
    if f is not None:
        fmt = f.get(WNS + "val", "")
    if st is not None:
        try:
            start = int(st.get(WNS + "val", ""))
        except ValueError:
            pass
    return fmt, start


def _docx_numbering(z: zipfile.ZipFile) -> dict[str, dict[int, tuple[str, int]]]:
    """numId -> {ilvl: (numFmt, start)} from word/numbering.xml; {} when absent/unreadable.

    Honours abstractNum <w:start>, and per-num <w:lvlOverride> (<w:startOverride>, <w:lvl>).
    """
    try:
        root = ET.fromstring(z.read("word/numbering.xml"))
    except (KeyError, ET.ParseError):
        return {}
    abstract: dict[str, dict[int, tuple[str, int]]] = {}
    for an in root.findall(WNS + "abstractNum"):
        levels = {}
        for lvl in an.findall(WNS + "lvl"):
            try:
                levels[int(lvl.get(WNS + "ilvl", "0"))] = _lvl_props(lvl)
            except ValueError:
                continue
        abstract[an.get(WNS + "abstractNumId", "")] = levels
    nums: dict[str, dict[int, tuple[str, int]]] = {}
    for num in root.findall(WNS + "num"):
        ref = num.find(WNS + "abstractNumId")
        if ref is None:
            continue
        levels = dict(abstract.get(ref.get(WNS + "val", ""), {}))
        for ov in num.findall(WNS + "lvlOverride"):
            try:
                ilvl = int(ov.get(WNS + "ilvl", "0"))
            except ValueError:
                continue
            props = levels.get(ilvl, ("", 1))
            lvl = ov.find(WNS + "lvl")
            if lvl is not None:
                props = _lvl_props(lvl, props)
            so = ov.find(WNS + "startOverride")
            if so is not None:
                try:
                    props = (props[0], int(so.get(WNS + "val", "")))
                except ValueError:
                    pass
            levels[ilvl] = props
        nums[num.get(WNS + "numId", "")] = levels
    return nums


def _ordered_fmt(fmt: str) -> bool:
    """Any counting format (decimal, letters, roman, ordinal, ...) -> ordered; CommonMark
    ordered items carry digits only, so the number is emitted in decimal."""
    return fmt not in ("", "bullet", "none")


def convert_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        numbering = _docx_numbering(z)
    body = root.find(WNS + "body")
    if body is None:
        raise ValueError("docx: no document body")
    blocks: list[tuple[str, str]] = []
    counters: dict[tuple[str, int], int] = {}  # (numId, ilvl) -> last number; reset off-list
    for el in body:
        if el.tag == WNS + "p":
            text = _docx_para_text(el).strip()
            ppr = el.find(WNS + "pPr")
            style = ""
            num_pr = None
            if ppr is not None:
                ps = ppr.find(WNS + "pStyle")
                style = (ps.get(WNS + "val") or "") if ps is not None else ""
                num_pr = ppr.find(WNS + "numPr")
            m = re.fullmatch(r"(?i)heading\s*([1-6])", style)
            if m and text:
                blocks.append(("h", "#" * int(m.group(1)) + " " + text))
                counters.clear()
            elif num_pr is not None or style.lower().startswith("list"):
                num_id, ilvl = "", 0
                if num_pr is not None:
                    nid, lv = num_pr.find(WNS + "numId"), num_pr.find(WNS + "ilvl")
                    num_id = (nid.get(WNS + "val") or "") if nid is not None else ""
                    try:
                        ilvl = max(0, min(8, int(lv.get(WNS + "val") or 0))) if lv is not None else 0
                    except ValueError:
                        ilvl = 0
                for key in [k for k in counters if k[0] == num_id and k[1] > ilvl]:
                    del counters[key]  # a shallower item restarts deeper levels
                fmt, start = numbering.get(num_id, {}).get(ilvl, ("", 1))
                if _ordered_fmt(fmt):
                    n = counters[(num_id, ilvl)] + 1 if (num_id, ilvl) in counters else start
                    counters[(num_id, ilvl)] = n
                    marker = f"{n}. "
                else:
                    marker = "- "
                blocks.append(("li", "   " * ilvl + marker + text))
            else:
                blocks.append(("p", text))
                if text:
                    counters.clear()
        elif el.tag == WNS + "tbl":
            rows = [[" ".join(_docx_para_text(p).strip() for p in tc.iter(WNS + "p")).strip()
                     for tc in tr.findall(WNS + "tc")]
                    for tr in el.findall(WNS + "tr")]
            blocks.append(("t", _table(rows)))
            counters.clear()
    return _join_blocks(blocks)


class _HTML(HTMLParser):
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self.buf: list[str] = []
        self.kind = "p"
        self.lists: list[list] = []  # [tag, counter]
        self.rows: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.skip = 0

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            text = _md_escape_line_starts(text)
            self.blocks.append((self.kind if self.kind != "li" else "li", self.prefix + text))
        self.kind, self.prefix = "p", ""

    prefix = ""

    def _out(self, s: str):
        (self.cell if self.cell is not None else self.buf).append(s)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.kind, self.prefix = "h", "#" * int(tag[1]) + " "
        elif tag in ("p", "div", "br") and self.cell is None:
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self._flush()
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.prefix = f"{self.lists[-1][1]}. "
            else:
                self.prefix = "- "
            self.kind = "li"
        elif tag == "table":
            self._flush()
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.rows.append([])
        elif tag in ("td", "th") and self.rows is not None:
            self.cell = []
        elif tag in ("strong", "b"):
            self._out("**")
        elif tag in ("em", "i"):
            self._out("*")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in ("p", "div", "li"):
            if self.cell is None:
                self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag in ("td", "th") and self.cell is not None and self.rows is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "table" and self.rows is not None:
            self.blocks.append(("t", _table(self.rows)))
            self.rows = None
        elif tag in ("strong", "b"):
            self._out("**")
        elif tag in ("em", "i"):
            self._out("*")

    def handle_data(self, data):
        if not self.skip:
            self._out(_md_escape(data, line_starts=False))


def convert_html(text: str) -> str:
    p = _HTML()
    p.feed(text)
    p.close()
    p._flush()
    return _join_blocks(p.blocks)


def convert_txt(text: str) -> str:
    paras = [p.strip("\n") for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))]
    return _join_blocks([("p", _md_escape(p)) for p in paras])


def _pdf_heading_level(line: str) -> int | None:
    line = line.strip()
    if not line or len(line) > 80 or "\n" in line or line[-1] in ".,;:!?":
        return None
    if not any(c.isalpha() for c in line):
        return None
    m = _NUMBERED_RE.match(line)
    if m:
        return min(6, 1 + len(m.group(1).split(".")))
    return 2 if len(line.split()) <= 10 else None


def pdf_text_to_markdown(pages) -> str:
    """pages: iterable of extracted page texts (consumed lazily)."""
    lines: list[str] = []
    for text in pages:
        for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if _PAGENUM_RE.match(line):
                continue
            lines.append(line.rstrip())
        lines.append("")
    paras: list[str] = []
    cur = ""
    for line in lines:
        if not line.strip():
            if cur:
                paras.append(cur)
            cur = ""
        elif cur.endswith("-") and len(cur) > 1 and cur[-2].isalpha() and line.lstrip()[:1].islower():
            cur = cur[:-1] + line.lstrip()
        elif cur and cur[-1] in ".!?:" and _NUMBERED_RE.match(line.strip()) \
                and _pdf_heading_level(line):
            paras.append(cur)  # numbered heading after a sentence end starts a new block
            cur = line.strip()
        else:
            cur = f"{cur}\n{line.strip()}" if cur else line.strip()
    if cur:
        paras.append(cur)
    blocks: list[tuple[str, str]] = []
    for i, para in enumerate(paras):
        first, _, rest = para.partition("\n")
        level = _pdf_heading_level(first)
        if level and rest.strip():
            blocks.append(("h", "#" * level + " " + _md_escape(first, line_starts=False)))
            para = rest
        elif level and i + 1 < len(paras) and _pdf_heading_level(paras[i + 1]) is None:
            blocks.append(("h", "#" * level + " " + _md_escape(para, line_starts=False)))
            continue
        blocks.append(("p", _md_escape(para)))
    return _join_blocks(blocks)


def convert_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("pdf: encrypted")
    md = pdf_text_to_markdown(page.extract_text() for page in reader.pages)
    if not md.strip():
        raise ValueError(OCR_REASON)
    return md


def count_headings(md: str) -> int:
    n, fence = 0, False
    for line in md.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and _HEADING_RE.match(line):
            n += 1
    return n


def node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(paths: list[str]) -> list[dict]:
    proc = subprocess.run(["node", str(CHECK_SCRIPT), *paths], capture_output=True,
                          text=True, check=True, timeout=600)
    return json.loads(proc.stdout)


def check_roundtrip(paths: list[str]) -> dict[str, dict | str]:
    results: dict[str, dict | str] = {}
    for i in range(0, len(paths), BATCH):
        batch = paths[i:i + BATCH]
        try:
            for r in _run_node(batch):
                results[r["path"]] = {k: v for k, v in r.items() if k != "path"}
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            for p in batch:
                results[p] = f"error: {e}"
    return results


def convert_one(src: Path) -> str:
    fmt = FORMATS[src.suffix.lower()]
    if fmt == "docx":
        return convert_docx(src)
    if fmt == "pdf":
        return convert_pdf(src)
    text = src.read_text(encoding="utf-8", errors="replace")
    if fmt == "html":
        return convert_html(text)
    if fmt == "txt":
        return convert_txt(text)
    return text


def convert_dir(src_dir: Path, out_dir: Path, check: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    written: set[str] = set()
    out_abs = out_dir.resolve()
    for src in sorted(p for p in src_dir.rglob("*")
                      if p.is_file() and not p.resolve().is_relative_to(out_abs)):
        ext = src.suffix.lower()
        entry = {"source": str(src), "output": None, "format": ext.lstrip(".") or None,
                 "status": "unsupported", "headings": None, "roundtrip": None}
        if ext == ".pdf" and not HAVE_PYPDF:
            entry["reason"] = PDF_REASON
        elif ext not in FORMATS:
            entry["reason"] = f"unsupported extension: {ext or '(none)'}"
        else:
            entry["format"] = FORMATS[ext]
            out = out_dir / f"{src.stem}.md"
            try:
                if out.name in written:
                    raise ValueError(f"output name collision: {out.name}")
                md = convert_one(src)
                out.write_text(md, encoding="utf-8")
                written.add(out.name)
                entry.update(status="ok", output=str(out), headings=count_headings(md))
            except Exception as e:  # noqa: BLE001 - per-file isolation is the contract
                entry.update(status="failed", error=f"{type(e).__name__}: {e}")
        entries.append(entry)
    ok = [e for e in entries if e["status"] == "ok"]
    if not check:
        for e in ok:
            e["roundtrip"] = "skipped: check disabled"
    elif not node_available():
        for e in ok:
            e["roundtrip"] = "skipped: node unavailable"
    else:
        res = check_roundtrip([e["output"] for e in ok])
        for e in ok:
            e["roundtrip"] = res.get(e["output"], "error: no result")
    summary = {s: sum(1 for e in entries if e["status"] == s)
               for s in ("ok", "failed", "unsupported")}
    return {"files": entries, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert SRC_DIR documents to Markdown in OUT_DIR")
    c.add_argument("src_dir")
    c.add_argument("out_dir")
    c.add_argument("--force", action="store_true", help="overwrite existing output")
    c.add_argument("--no-check", action="store_true", help="skip the docmodel round-trip check")
    args = parser.parse_args(argv)
    src, out = Path(args.src_dir), Path(args.out_dir)
    if not src.is_dir():
        print(f"error: source directory not found: {src}", file=sys.stderr)
        return 2
    if out.exists() and any(out.iterdir()) and not args.force:
        print(f"error: {out} is not empty; use --force to overwrite", file=sys.stderr)
        return 2
    report = convert_dir(src, out, check=not args.no_check)
    (out / REPORT_NAME).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))
    s = report["summary"]
    return 0 if s["failed"] == 0 and s["unsupported"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

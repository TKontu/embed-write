"""CO-04: convert source documents to Markdown for the corpus (stdlib only).

Formats: .docx (zipfile + xml.etree: paragraphs, Heading1..6 -> ATX headings,
bold/italic runs, list paragraphs -> ``-`` items, simple tables -> pipe tables),
.html/.htm (html.parser: h1-h6, p, ul/ol/li, table, strong/b, em/i), .txt
(blank-line separated paragraphs) and .md (copied). ``.pdf`` is reported
``unsupported`` until a dependency is decided; other extensions likewise.
Not handled: images, footnotes, tracked changes, nested lists/tables, merged
cells, hyperlinks (text kept), numbered DOCX lists (emitted as ``-``).

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

REPO = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO / "docmodel" / "scripts" / "check-roundtrip.js"
REPORT_NAME = "ingest_report.json"
BATCH = 50
FORMATS = {".docx": "docx", ".html": "html", ".htm": "html", ".txt": "txt", ".md": "md"}
PDF_REASON = "pdf: dependency decision pending"
WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_RE = re.compile(r"^#{1,6}(\s|$)")


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
        parts.append(_wrap(text, bold, italic))
    return "".join(parts).replace("****", "")


def convert_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(WNS + "body")
    if body is None:
        raise ValueError("docx: no document body")
    blocks: list[tuple[str, str]] = []
    for el in body:
        if el.tag == WNS + "p":
            text = _docx_para_text(el).strip()
            ppr = el.find(WNS + "pPr")
            style = ""
            numbered = False
            if ppr is not None:
                ps = ppr.find(WNS + "pStyle")
                style = (ps.get(WNS + "val") or "") if ps is not None else ""
                numbered = ppr.find(WNS + "numPr") is not None
            m = re.fullmatch(r"(?i)heading\s*([1-6])", style)
            if m and text:
                blocks.append(("h", "#" * int(m.group(1)) + " " + text))
            elif numbered or style.lower().startswith("list"):
                blocks.append(("li", "- " + text))
            else:
                blocks.append(("p", text))
        elif el.tag == WNS + "tbl":
            rows = [[" ".join(_docx_para_text(p).strip() for p in tc.iter(WNS + "p")).strip()
                     for tc in tr.findall(WNS + "tc")]
                    for tr in el.findall(WNS + "tr")]
            blocks.append(("t", _table(rows)))
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
            self._out(data)


def convert_html(text: str) -> str:
    p = _HTML()
    p.feed(text)
    p.close()
    p._flush()
    return _join_blocks(p.blocks)


def convert_txt(text: str) -> str:
    paras = [p.strip("\n") for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))]
    return _join_blocks([("p", p) for p in paras])


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
    for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
        ext = src.suffix.lower()
        entry = {"source": str(src), "output": None, "format": ext.lstrip(".") or None,
                 "status": "unsupported", "headings": None, "roundtrip": None}
        if ext == ".pdf":
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

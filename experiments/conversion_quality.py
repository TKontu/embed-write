"""CO-05: flag suspicious Markdown conversions from a CO-04 ingest report (stdlib only).

Reads an ``ingest_report.json`` written by ``experiments.ingest.convert_dir``
(``{"files": [{"source", "output", "format", "status", "headings",
"roundtrip", ...}], "summary": {...}}``) and writes a JSON list of documents
worth an expert spot-check. Each flagged document keeps its ``source`` and
``output`` paths and a list of ``flags`` ``{code, detail, line}``; ``line`` is
1-based where the flag refers to a line of the output, otherwise ``null``.
The summary counts documents checked (every report entry is examined),
documents with at least one flag and the occurrences of each flag code;
``unsupported`` entries have no text to check and yield no flag. Documents are
sorted by ``source``; flags by line then code. Details never quote more than a
short (<= 120 character) fragment, and the report never contains document body
text.

Heuristics (deterministic; thresholds are first guesses, unvalidated on the
real corpus — the expert decides whether a flagged document is acceptable):

- ``missing_output``: an ``ok`` entry has no output path, the file is gone, or
  it cannot be read.
- ``conversion_failed``: entry ``status`` is ``failed``; detail is its error.
- ``roundtrip_failed``: a roundtrip result is present and is not a success.
  Success is the string ``"ok"`` or a mapping with truthy ``parses`` and
  ``roundtrip_idempotent``; ``None`` and ``"skipped: ..."`` strings are silent.
- ``empty_output``: an ``ok`` output has no non-whitespace text.
- ``no_headings``: an ``ok`` entry with ``headings == 0`` and more than 200
  words outside fenced code.
- ``few_headings``: more than 1500 words outside fenced code with fewer than
  one heading per 1500 words; a long document with no headings fires both codes.
- ``broken_table``: within one Markdown table (consecutive lines whose first
  non-space character is ``|``), a row whose pipe-cell count differs from the
  header, or a table whose second row is not a ``| --- |`` separator; the line
  is the offending row, or the header when the separator is missing.
- ``merged_columns``: a prose line with three or more runs of four or more
  spaces between non-space characters (typical of merged PDF columns).
- ``long_line``: a non-table prose line longer than 2000 characters, which
  suggests lost paragraph breaks.

Lines inside ``` or ~~~ fences are ignored for every text flag. ``headings``
comes from the report entry when it is an integer, otherwise ATX headings
(``#``..``######`` followed by space or end of line) are counted while
streaming. Outputs are read one at a time, line by line: memory is bounded by
one line plus the current table block (header cell count, first line, a
separator-seen bit), never by the corpus.

Unwired by design: the CLI is the production caller; the expert reads OUT.json
and decides ([H], CO-05). No new dependency.

CLI: python -m experiments.conversion_quality check INGEST_REPORT OUT.json [--force]
Exit 0 on success, 2 on a missing/invalid report or on an existing OUT without
--force.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NO_HEADINGS_WORDS = 200
FEW_HEADINGS_WORDS = 1500
LONG_LINE_CHARS = 2000
MERGED_COLUMN_RUNS = 3
MERGED_COLUMN_SPACES = 4
DETAIL_CHARS = 120

_HEADING_RE = re.compile(r"^#{1,6}(\s|$)")
_SPACE_RUN_RE = re.compile(r"(?<=\S) {%d,}(?=\S)" % MERGED_COLUMN_SPACES)
_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _short(text: str) -> str:
    """Cap a detail string so it cannot carry a document line."""
    return text if len(text) <= DETAIL_CHARS else text[: DETAIL_CHARS - 3] + "..."


def _is_fence(line: str) -> bool:
    return line.lstrip().startswith(("```", "~~~"))


def _table_cells(line: str) -> list[str] | None:
    """Cells of a Markdown table row, or None when the line is not a row.

    A row is a stripped line that starts with ``|`` and has more than that one
    character; ``\\|`` is an escaped pipe inside a cell.
    """
    stripped = line.strip()
    if not stripped.startswith("|") or len(stripped) == 1:
        return None
    inner = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in inner:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
    cells.append("".join(current))
    return cells


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell.strip()) for cell in cells)


def _roundtrip_failed(value: object) -> bool:
    """True when a present CO-04 roundtrip result is not a success or a skip."""
    if value is None or value == "":
        return False
    if isinstance(value, str):
        return value != "ok" and not value.startswith("skipped")
    if isinstance(value, dict):
        return not (value.get("parses") and value.get("roundtrip_idempotent"))
    return True


def _roundtrip_detail(value: object) -> str:
    if isinstance(value, dict):
        return _short("roundtrip: " + json.dumps(value, sort_keys=True))
    return _short(f"roundtrip: {value}")


class _TextScan:
    """Streaming text statistics for one output file; never keeps the text."""

    def __init__(self) -> None:
        self.words = 0
        self.headings = 0
        self.has_text = False
        self.flags: list[dict] = []
        self._fence = False
        self._table: dict | None = None

    def _flag(self, code: str, detail: str, line: int) -> None:
        self.flags.append({"code": code, "detail": _short(detail), "line": line})

    def _close_table(self) -> None:
        table = self._table
        if table is not None and not table["separator"]:
            self._flag("broken_table", "table has no separator row", table["line"])
        self._table = None

    def feed(self, line: str, number: int) -> None:
        if _is_fence(line):
            self._close_table()
            self._fence = not self._fence
            return
        if self._fence:
            return
        cells = _table_cells(line)
        if cells is None:
            self._close_table()
            if not line.strip():
                return
            self.has_text = True
            self.words += len(line.split())
            if _HEADING_RE.match(line):
                self.headings += 1
            if len(line) > LONG_LINE_CHARS:
                self._flag("long_line", f"line has {len(line)} characters", number)
            runs = len(_SPACE_RUN_RE.findall(line))
            if runs >= MERGED_COLUMN_RUNS:
                self._flag("merged_columns",
                           f"{runs} runs of {MERGED_COLUMN_SPACES}+ spaces", number)
            return
        self.has_text = True
        self.words += len(line.split())
        table = self._table
        if table is None:
            self._table = {"line": number, "cells": len(cells), "rows": 1, "separator": False}
            return
        table["rows"] += 1
        if len(cells) != table["cells"]:
            self._flag("broken_table",
                       f"row has {len(cells)} cell(s); header has {table['cells']}", number)
        if table["rows"] == 2 and _is_separator(cells):
            table["separator"] = True

    def close(self) -> None:
        self._close_table()


def check_entry(entry: dict) -> dict:
    """Flag one ingest-report entry; returns ``{source, output, flags}``."""
    if not isinstance(entry, dict):
        raise ValueError(f"report entry is not an object: {entry!r}")
    flags: list[dict] = []
    status = entry.get("status")
    output = entry.get("output")

    if status == "failed":
        error = entry.get("error")
        detail = str(error) if error else "conversion failed"
        flags.append({"code": "conversion_failed", "detail": _short(detail), "line": None})
    if _roundtrip_failed(entry.get("roundtrip")):
        flags.append({"code": "roundtrip_failed",
                      "detail": _roundtrip_detail(entry.get("roundtrip")), "line": None})

    if status == "ok":
        if not output:
            flags.append({"code": "missing_output",
                          "detail": "entry has no output path", "line": None})
        else:
            path = Path(output)
            if not path.is_file():
                flags.append({"code": "missing_output", "detail": _short(str(path)), "line": None})
            else:
                scan = _TextScan()
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        for number, line in enumerate(handle, 1):
                            scan.feed(line.rstrip("\r\n"), number)
                    scan.close()
                except OSError as e:
                    flags.append({"code": "missing_output",
                                  "detail": _short(f"{path}: {e}"), "line": None})
                else:
                    flags.extend(scan.flags)
                    if not scan.has_text:
                        flags.append({"code": "empty_output",
                                      "detail": "output has no non-whitespace text", "line": None})
                    else:
                        headings = entry.get("headings")
                        count = headings if isinstance(headings, int) else scan.headings
                        if count == 0 and scan.words > NO_HEADINGS_WORDS:
                            flags.append({"code": "no_headings",
                                          "detail": f"{scan.words} words, no headings", "line": None})
                        if (scan.words > FEW_HEADINGS_WORDS
                                and count * FEW_HEADINGS_WORDS < scan.words):
                            flags.append({"code": "few_headings",
                                          "detail": f"{count} headings for {scan.words} words",
                                          "line": None})

    flags.sort(key=lambda flag: (flag["line"] or 0, flag["code"]))
    return {"source": entry.get("source"), "output": output, "flags": flags}


def build_report(report: dict) -> dict:
    """Build the suspicious-document report from a CO-04 ingest report."""
    if not isinstance(report, dict) or not isinstance(report.get("files"), list):
        raise ValueError("ingest report must be an object with a 'files' list")
    documents: list[dict] = []
    counts: dict[str, int] = {}
    for entry in report["files"]:
        record = check_entry(entry)
        if record["flags"]:
            documents.append(record)
            for flag in record["flags"]:
                counts[flag["code"]] = counts.get(flag["code"], 0) + 1
    documents.sort(key=lambda doc: (str(doc["source"]), str(doc["output"] or "")))
    return {
        "documents": documents,
        "summary": {
            "documents_checked": len(report["files"]),
            "documents_flagged": len(documents),
            "flags": {code: counts[code] for code in sorted(counts)},
        },
    }


def write_report(result: dict, out: str | Path, force: bool = False) -> None:
    """Write the result as sorted-key JSON; refuse to overwrite unless force."""
    data = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(out, "w" if force else "x", encoding="utf-8") as handle:
        handle.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.conversion_quality")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check", help="flag suspicious conversions from a CO-04 ingest report")
    check.add_argument("report", help="path to ingest_report.json")
    check.add_argument("out", help="path for the JSON suspicious-document report")
    check.add_argument("--force", action="store_true", help="overwrite an existing OUT.json")
    args = parser.parse_args(argv)
    if Path(args.out).exists() and not args.force:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        result = build_report(report)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        write_report(result, args.out, force=args.force)
    except FileExistsError:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""D-016 check: counts-only comparison of a pypdf ingest run against a MinerU ingest run.

CLI: ``python -m experiments.parser_compare compare PYPDF_OUT MINERU_OUT REPORT.json [--force]``

Reads each run's ``ingest_report.json`` and streams each converted ``.md`` one file at a time.
Per file and in total: status, error type name, parser used (MinerU run), ATX headings outside
fences, Markdown tables (blocks of consecutive ``|`` lines), ``$$`` formula blocks, words, and
dropped chrome counts. Files are keyed by an opaque index (``doc-01``...) in sorted source-name
order; the report holds no file names, titles or document text.

Unwired by design: a hand-run experiment (D-016 "Check", CO-04).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

REPORT_NAME = "ingest_report.json"
COUNTERS = ("headings", "tables", "formulas", "words")
_ATX = re.compile(r"^ {0,3}#{1,6}(\s|$)")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")


def count_markdown(lines: Iterable[str]) -> dict:
    c = dict.fromkeys(COUNTERS, 0)
    in_fence = in_table = in_formula = False
    for line in lines:
        c["words"] += len(line.split())
        s = line.strip()
        if _FENCE.match(line):
            in_fence = not in_fence
            in_table = False
            continue
        if in_fence:
            continue
        if in_formula:
            if s.endswith("$$"):
                in_formula = False
            continue
        if s.startswith("$$"):
            c["formulas"] += 1
            in_table = False
            if not (len(s) >= 4 and s.endswith("$$")):
                in_formula = True
            continue
        if s.startswith("|"):
            if not in_table:
                c["tables"] += 1
                in_table = True
            continue
        in_table = False
        if _ATX.match(line):
            c["headings"] += 1
    return c


def _load(run_dir: Path) -> dict[str, dict]:
    data = json.loads((run_dir / REPORT_NAME).read_text(encoding="utf-8"))
    return {Path(e["source"]).name: e for e in data["files"]}


def _side(entry: dict | None, with_parser: bool) -> dict:
    if entry is None:
        return {"status": "missing", **dict.fromkeys(COUNTERS)}
    d: dict = {"status": entry.get("status")}
    if entry.get("error"):
        d["error_type"] = str(entry["error"]).split(":", 1)[0].strip()
    out = entry.get("output")
    if entry.get("status") == "ok" and out and Path(out).is_file():
        with open(out, encoding="utf-8", errors="replace") as fh:
            d.update(count_markdown(fh))
    else:
        d.update(dict.fromkeys(COUNTERS))
    if with_parser:
        d["parser"] = entry.get("parser")
        if entry.get("mineru_error"):
            d["fallback_error"] = str(entry["mineru_error"])
        d["dropped"] = {str(k): int(v) for k, v in sorted((entry.get("dropped") or {}).items())}
    return d


def _totals(sides: list[dict], with_parser: bool) -> dict:
    t: dict = {"files": len(sides)}
    for s in ("ok", "failed", "unsupported", "missing"):
        t[s] = sum(1 for d in sides if d["status"] == s)
    for k in COUNTERS:
        t[k] = sum(d[k] or 0 for d in sides)
    t["error_types"] = dict(sorted(Counter(d["error_type"] for d in sides
                                           if "error_type" in d).items()))
    if with_parser:
        t["parser"] = dict(sorted(Counter(d["parser"] for d in sides if d["parser"]).items()))
        t["fallback_errors"] = dict(sorted(Counter(d["fallback_error"] for d in sides
                                                   if "fallback_error" in d).items()))
        dropped: Counter[str] = Counter()
        for d in sides:
            dropped.update(d["dropped"])
        t["dropped"] = dict(sorted(dropped.items()))
    return t


def compare(pypdf_dir: Path, mineru_dir: Path) -> dict:
    py, mu = _load(Path(pypdf_dir)), _load(Path(mineru_dir))
    docs = []
    for i, name in enumerate(sorted(set(py) | set(mu)), 1):
        docs.append({"doc": f"doc-{i:02d}", "pypdf": _side(py.get(name), False),
                     "mineru": _side(mu.get(name), True)})
    return {"documents": docs,
            "totals": {"pypdf": _totals([d["pypdf"] for d in docs], False),
                       "mineru": _totals([d["mineru"] for d in docs], True)}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m experiments.parser_compare")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("pypdf_out")
    c.add_argument("mineru_out")
    c.add_argument("report")
    c.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.report)
    if out.exists() and not a.force:
        print(f"error: {out} exists; use --force", file=sys.stderr)
        return 2
    try:
        report = compare(Path(a.pypdf_out), Path(a.mineru_out))
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {type(e).__name__}", file=sys.stderr)
        return 2
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

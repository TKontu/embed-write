"""Per-report metadata schema validation (CO-06). Stdlib only, offline.

A metadata file is JSONL: one object per line with exactly the fields
doc_id, genre, date, author_role, language, length. Genre values are not fixed here (CO-01).
The loader streams line by line and holds only the set of seen doc_ids.
Unwired by design; CO-08 splits, CO-09 statistics and AN-02 stratification will read it.

CLI: python -m experiments.corpus_metadata validate PATH [--genre GENRE]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

FIELDS = ("doc_id", "genre", "date", "author_role", "language", "length")
_STRING_FIELDS = ("doc_id", "genre", "author_role")
_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
# Primary language subtag (2-3 letters) plus optional alphanumeric subtags (2-8 chars).
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class MetadataError(ValueError):
    def __init__(self, message: str, line: int | None = None, path: str | os.PathLike | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.path = path

    def __str__(self) -> str:
        prefix = ""
        if self.path is not None:
            prefix += f"{self.path}:"
        if self.line is not None:
            prefix += f"{self.line}:"
        return f"{prefix} {self.message}" if prefix else self.message


def _valid_date(value: str) -> bool:
    m = _DATE_RE.match(value)
    if not m:
        return False
    year, month, day = m.group(1), m.group(2), m.group(3)
    try:
        _dt.date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return False
    return True


def validate_record(record: object, genre: str | None = None) -> list[str]:
    """Return a list of error messages for one record (empty when valid)."""
    if not isinstance(record, dict):
        return [f"record must be a JSON object, got {type(record).__name__}"]
    errors: list[str] = []
    for name in FIELDS:
        if name not in record:
            errors.append(f"missing field: {name}")
    for name in sorted(set(record) - set(FIELDS)):
        errors.append(f"unknown field: {name}")
    for name in _STRING_FIELDS:
        if name in record:
            v = record[name]
            if not isinstance(v, str) or not v.strip():
                errors.append(f"{name} must be a non-empty string")
    if "date" in record:
        v = record["date"]
        if not isinstance(v, str) or not _valid_date(v):
            errors.append(f"date must be ISO 8601 YYYY, YYYY-MM or YYYY-MM-DD, got {v!r}")
    if "language" in record:
        v = record["language"]
        if not isinstance(v, str) or not _LANG_RE.match(v):
            errors.append(f"language must be a BCP-47-like tag (e.g. fi, en-GB), got {v!r}")
    if "length" in record:
        v = record["length"]
        if not isinstance(v, int) or isinstance(v, bool):
            errors.append(f"length must be an integer word count, got {type(v).__name__}")
        elif v < 0:
            errors.append(f"length must be non-negative, got {v}")
    if genre is not None and isinstance(record.get("genre"), str) and record["genre"] != genre:
        errors.append(f"genre mismatch: expected {genre!r}, got {record['genre']!r}")
    return errors


def _scan(path: str | os.PathLike, genre: str | None) -> Iterator[tuple[int, dict | None, list[str]]]:
    seen: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                yield lineno, None, [f"invalid JSON: {exc.msg}"]
                continue
            errors = validate_record(record, genre=genre)
            if isinstance(record, dict):
                doc_id = record.get("doc_id")
                if isinstance(doc_id, str):
                    if doc_id in seen:
                        errors.append(f"duplicate doc_id: {doc_id!r}")
                    seen.add(doc_id)
            yield lineno, (record if isinstance(record, dict) else None), errors


def validate_file(path: str | os.PathLike, genre: str | None = None) -> list[MetadataError]:
    """Validate a JSONL metadata file; return all line-numbered errors."""
    out: list[MetadataError] = []
    for lineno, _record, errors in _scan(path, genre):
        out.extend(MetadataError(e, line=lineno, path=path) for e in errors)
    return out


def iter_records(path: str | os.PathLike, genre: str | None = None) -> Iterator[dict]:
    """Stream valid records; raise MetadataError at the first invalid line."""
    for lineno, record, errors in _scan(path, genre):
        if errors:
            raise MetadataError("; ".join(errors), line=lineno, path=path)
        yield record  # type: ignore[misc]


def word_count(text: str) -> int:
    """Whitespace word count, for filling `length` from Document.text."""
    return len(text.split())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.corpus_metadata")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate a JSONL metadata file")
    v.add_argument("path")
    v.add_argument("--genre", default=None, help="require every record to have this genre")
    args = parser.parse_args(argv)
    if not Path(args.path).is_file():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    errors = validate_file(args.path, genre=args.genre)
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        print(f"{len(errors)} error(s)", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

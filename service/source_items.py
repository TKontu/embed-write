"""Source-item schema and validation (todo-09 SR-02).

Architecture §5.1: source items are stored as first-class objects; text spans link to the items
they rest on. This module only defines and validates the record. Pure stdlib, local only (I9).

Schema (one JSON object per item):

    {
      "id":         string matching ^[A-Za-z0-9][A-Za-z0-9._-]*$, unique within a collection
      "type":       one of ALLOWED_TYPES
      "content":    non-empty string
      "units":      list of canonical unit strings (may be empty)
      "provenance": {
          "source":      non-empty string
          "locator":     optional non-empty string (page, cell, timestamp, ...)
          "recorded_by": non-empty string
          "recorded_at": optional ISO 8601 date or datetime string
      }
    }

Keys starting with "_" are comments and ignored (at both levels); any other unknown key is
rejected. bool is never accepted where a string is required.

ALLOWED_TYPES is provisional until SR-01 [H] decides what counts as a source item.

Units must already be canonical: the canonical set is ``service.support_check.UNITS`` plus "%",
the same table ``service.quantities`` canonicalises to. An alias listed in
``service.quantities.UNIT_ALIASES`` (e.g. "millimetre") is rejected with the canonical form in
the message rather than silently rewritten, so stored items equal what was written and to_dict
round-trips exactly. quantities exposes no canonicalisation function (``_CANON`` is private), so
the public tables are combined here; quantities.py is not modified.

Unwired by design until SR-03 (import paths); the future support matcher (AD-02/AD-05) is the
other production caller.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from service.quantities import UNIT_ALIASES
from service.support_check import UNITS

ALLOWED_TYPES = ("measurement", "test_result", "observation", "photo_note", "document_ref")
"""Provisional until SR-01 [H]."""

CANONICAL_UNITS = frozenset((*UNITS, "%"))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_FIELDS = ("id", "type", "content", "units", "provenance")
_PROV_REQUIRED = ("source", "recorded_by")
_PROV_FIELDS = ("source", "locator", "recorded_by", "recorded_at")


class SourceItemError(ValueError):
    """Raised for an invalid source item; the message starts with the field path."""


@dataclass(frozen=True)
class Provenance:
    source: str
    locator: str | None
    recorded_by: str
    recorded_at: str | None


@dataclass(frozen=True)
class SourceItem:
    id: str
    type: str
    content: str
    units: tuple[str, ...]
    provenance: Provenance


def _fail(field, why):
    raise SourceItemError(f"{field}: {why}")


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        _fail(field, "must be a non-empty string")
    return value


def _check_keys(obj, allowed, prefix):
    for key in obj:
        if not isinstance(key, str) or (not key.startswith("_") and key not in allowed):
            _fail(f"{prefix}{key}", "unknown field")


def _iso(value, field):
    if not isinstance(value, str):
        _fail(field, "must be an ISO 8601 date or datetime string")
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(field, f"{value!r} is not an ISO 8601 date or datetime")
    return value


def _provenance(p):
    if not isinstance(p, dict):
        _fail("provenance", "must be an object")
    _check_keys(p, _PROV_FIELDS, "provenance.")
    for key in _PROV_REQUIRED:
        if key not in p:
            _fail(f"provenance.{key}", "required field missing")
    locator = p.get("locator")
    if locator is not None:
        _text(locator, "provenance.locator")
    recorded_at = p.get("recorded_at")
    if recorded_at is not None:
        _iso(recorded_at, "provenance.recorded_at")
    return Provenance(_text(p["source"], "provenance.source"), locator,
                      _text(p["recorded_by"], "provenance.recorded_by"), recorded_at)


def validate_source_item(obj: dict) -> SourceItem:
    """Validate one parsed item; return a SourceItem or raise SourceItemError."""
    if not isinstance(obj, dict):
        _fail("<root>", "must be a JSON object")
    _check_keys(obj, _FIELDS, "")
    for key in _FIELDS:
        if key not in obj:
            _fail(key, "required field missing")
    item_id = obj["id"]
    if not isinstance(item_id, str) or not _ID.match(item_id):
        _fail("id", "must be a string matching ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    if not isinstance(obj["type"], str) or obj["type"] not in ALLOWED_TYPES:
        _fail("type", f"must be one of {', '.join(ALLOWED_TYPES)} (provisional until SR-01)")
    content = _text(obj["content"], "content")
    units = obj["units"]
    if not isinstance(units, list):
        _fail("units", "must be a list of unit strings")
    for i, u in enumerate(units):
        if not isinstance(u, str):
            _fail(f"units[{i}]", "must be a string")
        if u not in CANONICAL_UNITS:
            if u in UNIT_ALIASES:
                _fail(f"units[{i}]", f'non-canonical alias {u!r}; write "{UNIT_ALIASES[u]}"')
            _fail(f"units[{i}]", f"unknown unit {u!r}")
    return SourceItem(item_id, obj["type"], content, tuple(units), _provenance(obj["provenance"]))


def _validate_all(pairs):
    seen = set()
    out = []
    for where, obj in pairs:
        try:
            item = validate_source_item(obj)
        except SourceItemError as exc:
            raise SourceItemError(f"{where}{exc}") from exc
        if item.id in seen:
            _fail(f"{where}id", f'duplicate id "{item.id}"')
        seen.add(item.id)
        out.append(item)
    return tuple(out)


def validate_source_items(objs) -> tuple[SourceItem, ...]:
    """Validate an iterable of parsed items; errors are prefixed "[index].", ids must be unique."""
    return _validate_all((f"[{i}].", obj) for i, obj in enumerate(objs))


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise SourceItemError(f"line {n}: invalid JSON: {exc}") from exc
                yield f"line {n}: ", obj
    except OSError as exc:
        raise SourceItemError(f"<file> {path}: {exc}") from exc


def load_source_items(path) -> tuple[SourceItem, ...]:
    """Stream a JSON Lines file (blank lines ignored); errors name the line number."""
    return _validate_all(_jsonl(path))


def to_dict(item: SourceItem) -> dict:
    """Plain dict form; ``validate_source_item(to_dict(item)) == item``."""
    p = item.provenance
    prov = {"source": p.source, "recorded_by": p.recorded_by}
    if p.locator is not None:
        prov["locator"] = p.locator
    if p.recorded_at is not None:
        prov["recorded_at"] = p.recorded_at
    return {"id": item.id, "type": item.type, "content": item.content,
            "units": list(item.units), "provenance": prov}

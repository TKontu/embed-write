"""Read gate threshold records; production caller: runner.run_gate (ST-01)."""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import re

DEFAULT_ROOT = Path(__file__).with_name("preregistration")


class PreregistrationError(ValueError):
    """A gate has no valid, confirmed threshold record."""


def load(gate: str, root=DEFAULT_ROOT) -> dict:
    """Load and validate a confirmed record from ``root/<gate>.json``."""
    if not isinstance(gate, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", gate):
        raise PreregistrationError("invalid gate id")
    path = Path(root) / f"{gate}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PreregistrationError(f"{gate}: cannot read valid JSON at {path}") from error
    if not isinstance(record, dict):
        raise PreregistrationError(f"{gate}: record must be an object")
    for field in ("gate", "threshold", "metric", "confirmed_by", "confirmed_at"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise PreregistrationError(f"{gate}: {field} must be nonempty text")
    if record["gate"] != gate:
        raise PreregistrationError(f"{gate}: record gate id does not match")
    timestamp = record["confirmed_at"]
    try:
        if "T" not in timestamp:
            raise ValueError("date-time required")
        confirmed_at = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if confirmed_at.utcoffset() != datetime.timedelta(0):
            raise ValueError("UTC required")
    except ValueError as error:
        raise PreregistrationError(f"{gate}: confirmed_at must be ISO 8601 UTC") from error
    if "recorded_commit" in record and (
        not isinstance(record["recorded_commit"], str) or not record["recorded_commit"].strip()
    ):
        raise PreregistrationError(f"{gate}: recorded_commit must be nonempty text if present")
    return record


def require_confirmed(gate: str, root=DEFAULT_ROOT) -> dict:
    """Refuse execution unless the gate has a valid confirmed record."""
    return load(gate, root=root)

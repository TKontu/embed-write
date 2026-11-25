"""Gate registry loader and schema validator (X-01, architecture invariant I6).

Unwired by design: X-02 wires ``load_registry`` into the CI flag check.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = Path(__file__).resolve().with_name("registry.toml")

STATUSES = frozenset({"pending", "running", "passed", "failed", "waived"})
_ID = re.compile(r"G-\d\d")
_FLAG = re.compile(r"[a-z0-9_]+")
_FIELDS = {"id", "title", "status", "threshold", "result_doc", "flags_unlocked"}


class RegistryError(ValueError):
    """The registry file violates the gate schema."""


@dataclass(frozen=True)
class Gate:
    id: str
    title: str
    status: str
    threshold: str | None
    result_doc: str
    flags_unlocked: tuple[str, ...]


def _fail(gate_id: str, field: str, msg: str) -> RegistryError:
    return RegistryError(f"gate {gate_id}: field {field}: {msg}")


def _gate(entry: object, index: int, root: Path) -> Gate:
    if not isinstance(entry, dict):
        raise RegistryError(f"gate #{index}: entry is not a table")
    gid = entry.get("id")
    if not isinstance(gid, str) or not _ID.fullmatch(gid):
        raise _fail(repr(gid) if not isinstance(gid, str) else gid, "id", "must match G-\\d\\d")
    unknown = sorted(set(entry) - _FIELDS)
    if unknown:
        raise _fail(gid, unknown[0], "unknown field")
    title = entry.get("title")
    if not isinstance(title, str) or not title.strip():
        raise _fail(gid, "title", "must be a nonempty string")
    status = entry.get("status")
    if status not in STATUSES:
        raise _fail(gid, "status", f"{status!r} not in {sorted(STATUSES)}")
    threshold = entry.get("threshold")
    if threshold is not None and not isinstance(threshold, str):
        raise _fail(gid, "threshold", "must be a string or absent (null)")
    result_doc = entry.get("result_doc")
    expected = f"experiments/results/{gid}.md"
    if result_doc != expected:
        raise _fail(gid, "result_doc", f"must be {expected!r}, got {result_doc!r}")
    if status == "passed" and not (root / result_doc).is_file():
        raise _fail(gid, "result_doc", f"status passed but {result_doc} does not exist")
    flags = entry.get("flags_unlocked")
    if not isinstance(flags, list):
        raise _fail(gid, "flags_unlocked", "must be a list")
    for flag in flags:
        if not isinstance(flag, str) or not _FLAG.fullmatch(flag):
            raise _fail(gid, "flags_unlocked", f"{flag!r} must match [a-z0-9_]+")
    return Gate(gid, title, status, threshold, result_doc, tuple(flags))


def load_registry(path: Path | str = DEFAULT_PATH, root: Path | str = REPO_ROOT) -> list[Gate]:
    """Load and validate the registry; ``root`` resolves result_doc paths."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("gate")
    if not isinstance(entries, list) or not entries:
        raise RegistryError("registry: no [[gate]] entries")
    gates: list[Gate] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        gate = _gate(entry, index, Path(root))
        if gate.id in seen:
            raise _fail(gate.id, "id", "duplicate id")
        seen.add(gate.id)
        gates.append(gate)
    return gates

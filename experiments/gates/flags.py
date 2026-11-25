"""Flag definitions and the gate check (X-02, architecture invariant I6).

Each flag names the gate that removes it; a flag may be enabled only once its gate reads
``passed``. Called by scripts/check_flags.py (nightly CI and tests/test_check_flags.py).
``load_flags`` has no product caller yet: unwired by design until the first gated capability
lands and reads its flag.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from experiments.gates.registry import Gate

DEFAULT_PATH = Path(__file__).resolve().with_name("flags.toml")

_NAME = re.compile(r"[a-z0-9_]+")
_FIELDS = {"name", "gate", "enabled", "description"}


class FlagError(ValueError):
    """The flags file violates the flag schema."""


@dataclass(frozen=True)
class Flag:
    name: str
    gate: str
    enabled: bool
    description: str


def _fail(flag: str, field: str, msg: str) -> FlagError:
    return FlagError(f"flag {flag}: field {field}: {msg}")


def _flag(entry: object, index: int, gate_ids: set[str]) -> Flag:
    if not isinstance(entry, dict):
        raise FlagError(f"flag #{index}: entry is not a table")
    name = entry.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        label = name if isinstance(name, str) and name else f"#{index}"
        raise _fail(label, "name", f"{name!r} must match [a-z0-9_]+")
    unknown = sorted(set(entry) - _FIELDS)
    if unknown:
        raise _fail(name, unknown[0], "unknown field")
    gate = entry.get("gate")
    if not isinstance(gate, str) or gate not in gate_ids:
        raise _fail(name, "gate", f"{gate!r} is not a gate in the registry")
    enabled = entry.get("enabled")
    if not isinstance(enabled, bool):
        raise _fail(name, "enabled", "must be a boolean")
    description = entry.get("description")
    if not isinstance(description, str) or not description.strip():
        raise _fail(name, "description", "must be a nonempty string")
    return Flag(name, gate, enabled, description)


def load_flags(path: Path | str, gates: list[Gate]) -> list[Flag]:
    """Load and validate flags against the (already validated) gate registry."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("flag", [])
    if not isinstance(entries, list):
        raise FlagError("flags: 'flag' must be an array of [[flag]] tables")
    gate_ids = {g.id for g in gates}
    flags: list[Flag] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        flag = _flag(entry, index, gate_ids)
        if flag.name in seen:
            raise _fail(flag.name, "name", "duplicate name")
        seen.add(flag.name)
        flags.append(flag)
    return flags


def check(flags: list[Flag], gates: list[Gate]) -> list[str]:
    """Return one violation message per enabled flag whose gate is not ``passed``."""
    status = {g.id: g.status for g in gates}
    return [
        f"flag {f.name} is enabled but gate {f.gate} is {status[f.gate]}, not passed"
        for f in flags
        if f.enabled and status[f.gate] != "passed"
    ]

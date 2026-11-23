"""Continuous evaluation: decide when a gate must re-run and switch flags off on regression (CE-01).

Invariant I6 (docs/architecture.md): a capability whose gate has not passed stays behind a flag.
This module can only turn flags *off*. Enabling a flag after a passing re-run is the operator's
act; ``FlagRegistry.apply_rerun`` returns a note instead of enabling anything.

Connections: ``rerun_required`` and ``FlagRegistry`` are unwired by design until CE-02 (nightly
run) and the I6 CI check wire them. The registry is in-memory only; persistence is out of scope.
Memory is O(flags).
"""

from __future__ import annotations

import copy

RERUN_KEYS = ("modelVersion", "inventoryVersion", "method")


def rerun_required(previous: dict, current: dict) -> list[str]:
    """Return which of modelVersion / inventoryVersion / method differ between two run descriptors.

    A key missing on either side counts as changed. Order follows ``RERUN_KEYS``.
    """
    return [k for k in RERUN_KEYS if k not in previous or k not in current or previous[k] != current[k]]


class FlagRegistry:
    """Flags bound to gates: ``{flag_name: {"gate": "G-XX", "enabled": bool, "reason": str}}``."""

    def __init__(self) -> None:
        self._flags: dict[str, dict] = {}

    @classmethod
    def from_dict(cls, data: dict) -> "FlagRegistry":
        reg = cls()
        for name, entry in data.items():
            if not isinstance(entry, dict):
                raise ValueError(f"flag {name!r}: entry must be a dict")
            gate, enabled, reason = entry.get("gate"), entry.get("enabled"), entry.get("reason", "")
            if not isinstance(gate, str) or not gate:
                raise ValueError(f"flag {name!r}: 'gate' must be a non-empty string")
            if not isinstance(enabled, bool):
                raise ValueError(f"flag {name!r}: 'enabled' must be a bool")
            if not isinstance(reason, str):
                raise ValueError(f"flag {name!r}: 'reason' must be a string")
            reg._flags[name] = {"gate": gate, "enabled": enabled, "reason": reason}
        return reg

    def to_dict(self) -> dict:
        return copy.deepcopy(self._flags)

    def apply_rerun(self, gate: str, passed: bool, reason: str) -> list[str]:
        """Apply a gate re-run outcome to every flag bound to ``gate``; return notes.

        ``passed=False`` disables each bound flag and records ``reason``; a flag that was already
        disabled keeps its prior reason with the regression appended. ``passed=True`` changes
        nothing; a disabled bound flag yields a note that enabling it is the operator's act.
        Flags bound to other gates are untouched.
        """
        notes = []
        for name, entry in self._flags.items():
            if entry["gate"] != gate:
                continue
            if not passed:
                was = entry["enabled"]
                entry["enabled"] = False
                note = f"{gate} re-run regressed: {reason}"
                # An already-disabled flag keeps its history: append, never overwrite.
                entry["reason"] = note if was or not entry["reason"] else f"{entry['reason']}; {note}"
                notes.append(f"{name}: {'disabled' if was else 'stays disabled'} ({gate} regressed)")
            elif not entry["enabled"]:
                notes.append(f"{name}: {gate} re-run passed; enabling is the operator's act")
        return notes

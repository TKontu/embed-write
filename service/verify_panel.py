"""Verification panel (VF-07): each axis side by side, with value, confidence and method link.

``build_panel(original, candidate)`` returns one :class:`VerificationPanel` holding an ordered
tuple of :class:`AxisEntry`, one per axis of the §5.9 table in ``docs/architecture.md``, in that
table's order. Each axis is a separate, separately validated check: an entry carries its own
value, its own confidence label and a link to the method that defines it. Nothing here combines,
weights, ranks or summarises the axes (VF-10), and the panel never names a preferred candidate.

Axes with no implementation yet (VF-01 move, VF-02 meaning, VF-04 register, VF-05 grammar) are
present with ``status="not_available"``, ``value=None`` and ``confidence=None`` -- never omitted
and never guessed, so a consumer cannot mistake an absent check for a passing one.

Implemented axes:

- **Support preserved** -- :func:`service.support_check.support_diff`. Value:
  ``{"preserved": bool, "missing": {token: count}, "added": {token: count}}``. Confidence
  ``"deterministic-literal"``: the check is an exact token multiset diff, so only literal numbers,
  units, links and citation keys are covered; the "still entailed" path (a paraphrased number, a
  converted unit) is not checked and waits for VF-02/G-08 (see the entry's ``note``).
- **Length delta** -- :func:`service.length_delta.length_delta`. Value: the ``LengthDelta`` fields
  (word/character counts, signed deltas, candidate/original ratios). Confidence
  ``"deterministic"``: counting is exact; the numbers are reported, not judged.

The panel-level ``methods`` tuple links ``docs/methods/llm-not-final-judge.md`` (VF-11): an LLM is
not the final judge of a candidate's quality, the expert decides.

Unwired by design until UX-01/VF-08 consume ``build_panel``. Inputs are a single passage pair; no
corpus loops, no I/O, no network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from service.length_delta import length_delta
from service.support_check import support_diff

ARCHITECTURE_ANCHOR = "docs/architecture.md#59-proposals-and-verification"
METHODS_DOC = "docs/methods/llm-not-final-judge.md"

#: (axis label, todo item) in the order of the §5.9 table.
AXIS_ORDER: tuple[str, ...] = (
    "Move preserved",
    "Meaning preserved",
    "Support preserved",
    "Register fit",
    "Grammar",
    "Length delta",
)

_AXIS_ITEMS = {
    "Move preserved": "VF-01",
    "Meaning preserved": "VF-02",
    "Support preserved": "VF-03",
    "Register fit": "VF-04",
    "Grammar": "VF-05",
    "Length delta": "VF-06",
}

_SUPPORT_NOTE = (
    "literal token diff only (numbers with units, percentages, links, citation keys); "
    "the \"still entailed\" path -- paraphrased numbers, converted units -- is not checked "
    "and waits for VF-02/G-08"
)
_LENGTH_NOTE = "reported counts and deltas; no threshold, verdict or judgment"


@dataclass(frozen=True)
class AxisEntry:
    """One verification axis: its own value, confidence and method link. Never combined."""

    axis: str
    status: str
    value: dict[str, Any] | None
    confidence: str | None
    method_link: str
    implementation: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "status": self.status,
            "value": self.value,
            "confidence": self.confidence,
            "method_link": self.method_link,
            "implementation": self.implementation,
            "note": self.note,
        }


@dataclass(frozen=True)
class VerificationPanel:
    """All §5.9 axes for one (original, candidate) pair, side by side and in table order."""

    axes: tuple[AxisEntry, ...]
    methods: tuple[str, ...]

    def entry(self, axis: str) -> AxisEntry:
        """Return the entry for ``axis`` (the §5.9 label); ``KeyError`` if absent."""
        for entry in self.axes:
            if entry.axis == axis:
                return entry
        raise KeyError(axis)

    def to_dict(self) -> dict[str, Any]:
        return {
            "axes": [entry.to_dict() for entry in self.axes],
            "methods": list(self.methods),
        }


def _support_entry(original: str, candidate: str) -> AxisEntry:
    diff = support_diff(original, candidate)
    return AxisEntry(
        axis="Support preserved",
        status="ok",
        value={
            "preserved": diff.preserved,
            "missing": dict(sorted(diff.missing.items())),
            "added": dict(sorted(diff.added.items())),
        },
        confidence="deterministic-literal",
        method_link=ARCHITECTURE_ANCHOR,
        implementation="service/support_check.py",
        note=_SUPPORT_NOTE,
    )


def _length_entry(original: str, candidate: str) -> AxisEntry:
    delta = length_delta(original, candidate)
    return AxisEntry(
        axis="Length delta",
        status="ok",
        value=asdict(delta),
        confidence="deterministic",
        method_link=ARCHITECTURE_ANCHOR,
        implementation="service/length_delta.py",
        note=_LENGTH_NOTE,
    )


_BUILDERS: dict[str, Callable[[str, str], AxisEntry]] = {
    "Support preserved": _support_entry,
    "Length delta": _length_entry,
}


def _unavailable(axis: str) -> AxisEntry:
    return AxisEntry(
        axis=axis,
        status="not_available",
        value=None,
        confidence=None,
        method_link=ARCHITECTURE_ANCHOR,
        implementation=None,
        note=f"no implementation yet ({_AXIS_ITEMS[axis]})",
    )


def build_panel(original: str, candidate: str) -> VerificationPanel:
    """Assemble the verification panel for one passage pair; one entry per §5.9 axis."""
    entries = tuple(
        _BUILDERS[axis](original, candidate) if axis in _BUILDERS else _unavailable(axis)
        for axis in AXIS_ORDER
    )
    return VerificationPanel(axes=entries, methods=(METHODS_DOC,))

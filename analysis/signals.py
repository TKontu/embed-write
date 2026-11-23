"""Signal type, signal-kind registry and naming lint (SF-01..SF-03).

Invariants (docs/architecture.md): I4 every signal carries confidence,
method_ref and layer; I8 no display name implies a quality judgement.
Unwired by design; SF-04 consumes ``registered_kinds``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

LAYERS = ("provisional", "confirmed")
BANNED_WORDS = ("quality", "score", "correct", "coherence")


def lint_display_name(name: str) -> str:
    """Return ``name`` if clean; raise ValueError if it contains a banned word.

    Case-insensitive substring match, so "Scored" and "incorrect" fail.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"display name must be a non-empty string: {name!r}")
    lowered = name.lower()
    hits = [w for w in BANNED_WORDS if w in lowered]
    if hits:
        raise ValueError(
            f"display name {name!r} contains banned word(s) {hits} (invariant I8)"
        )
    return name


@dataclass(frozen=True)
class SignalKind:
    name: str
    gate: tuple[str, ...]
    display_name: str
    definition: str
    known_limits: str


_REGISTRY: dict[str, SignalKind] = {}


def register_kind(kind: SignalKind) -> SignalKind:
    if not isinstance(kind.name, str) or not kind.name.strip():
        raise ValueError("kind name must be a non-empty string")
    if kind.name in _REGISTRY:
        raise ValueError(f"signal kind {kind.name!r} already registered")
    if not kind.gate or not all(isinstance(g, str) and g.strip() for g in kind.gate):
        raise ValueError(f"kind {kind.name!r} must declare at least one gate")
    for field in ("definition", "known_limits"):
        value = getattr(kind, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"kind {kind.name!r} must declare {field}")
    lint_display_name(kind.display_name)
    _REGISTRY[kind.name] = kind
    return kind


def get_kind(name: str) -> SignalKind:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unregistered signal kind {name!r}") from None


def registered_kinds() -> tuple[SignalKind, ...]:
    return tuple(_REGISTRY.values())


@dataclass(frozen=True)
class Signal:
    node_id: str
    level: str
    kind: str
    value: Any
    confidence: float
    method_ref: str
    layer: str
    computed_at: str

    def __post_init__(self) -> None:
        if self.kind not in _REGISTRY:
            raise ValueError(f"unregistered signal kind {self.kind!r}")
        c = self.confidence
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            raise TypeError(f"confidence must be a number, got {type(c).__name__}")
        if math.isnan(c) or not 0.0 <= c <= 1.0:
            raise ValueError(f"confidence {c!r} outside [0, 1]")
        if not isinstance(self.method_ref, str) or not self.method_ref.strip():
            raise ValueError("method_ref must be a non-empty string")
        if self.layer not in LAYERS:
            raise ValueError(f"layer must be one of {LAYERS}, got {self.layer!r}")


for _kind in (
    SignalKind("move", ("G-01", "G-04"), "Move",
               "Rhetorical move a unit performs within its section.",
               "Label set is genre-specific; fast layer sees no section context."),
    SignalKind("sequence_fit", ("G-05",), "Sequence fit",
               "How closely the order of move labels matches the genre's typical sequence.",
               "Depends on upstream move labels; atypical order can be intentional."),
    SignalKind("register_fit", ("G-06",), "Register fit",
               "Style distance of a passage from the genre profile.",
               "Distance is not a defect; profile reflects its reference corpus only."),
    SignalKind("support", ("G-07",), "Support",
               "Whether candidate evidence in the text entails a conclusion.",
               "Only finds evidence inside the document; retrieval misses lower recall."),
    SignalKind("redundancy", ("G-04",), "Redundancy",
               "Within-level similarity between units across sections.",
               "Fast layer cannot tell repetition from intentional recap."),
    SignalKind("topic", ("G-11",), "Topic",
               "Optional overlay of within-level clusters.",
               "Clusters are unlabelled and unstable across runs; no slow layer."),
):
    register_kind(_kind)
del _kind

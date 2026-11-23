"""SP-01: unwired by design until the move classifier and SP-02 consume it.

Residuals: trusts upstream move labels and their confidence; no classification,
retrieval, entailment or support signals (SP-05). Defaults are genre-independent;
callers supply the genre's claim moves. One document and one level per call;
document identity is a caller responsibility. Synthetic tests only, no private
corpus/model path exercised. G-07 remains unevaluated. Claims are selection
records, not I4 signals; SP-05 must supply signal method and layer metadata.

One pass, O(sentences) time and O(claims + ids) memory for one document.
"""

from collections.abc import Iterable, Set
from dataclasses import dataclass


DEFAULT_CLAIM_MOVES = frozenset({"conclusion", "interpretation"})


def _validate_confidence(value: float, name: str) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be a finite number in [0, 1]")


@dataclass(frozen=True)
class LabelledSentence:
    node_id: str
    level: str
    move: str
    confidence: float

    def __post_init__(self) -> None:
        for name in ("node_id", "level", "move"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        _validate_confidence(self.confidence, "confidence")


@dataclass(frozen=True)
class Claim:
    node_id: str
    level: str
    move: str
    confidence: float


def select_claims(
    sentences: Iterable[LabelledSentence],
    *,
    claim_moves: Set[str] = DEFAULT_CLAIM_MOVES,
    min_confidence: float = 0.0,
) -> list[Claim]:
    """Select exact move matches, validating identity and level before filtering."""
    if (not isinstance(claim_moves, Set) or not claim_moves
            or any(not isinstance(move, str) or not move for move in claim_moves)):
        raise ValueError("claim_moves must be a non-empty set of non-empty strings")
    _validate_confidence(min_confidence, "min_confidence")
    moves = frozenset(claim_moves)
    claims = []
    ids = set()
    level = None
    for sentence in sentences:
        if sentence.node_id in ids:
            raise ValueError(f"duplicate node_id: {sentence.node_id!r}")
        ids.add(sentence.node_id)
        if level is None:
            level = sentence.level
        elif sentence.level != level:
            raise ValueError("sentences must share one level")
        if sentence.move in moves and sentence.confidence >= min_confidence:
            claims.append(Claim(sentence.node_id, sentence.level,
                                sentence.move, sentence.confidence))
    return claims

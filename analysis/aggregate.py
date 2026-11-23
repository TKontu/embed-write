"""Paragraph and section move labels by aggregating sentence labels (PT-06, I2).

Labels are derived only from sentence move labels, never from vectors: any
LevelVector (or other non-SentenceLabel item) is rejected with TypeError.

Unwired by design until PT-02: its classifier output is the production caller,
feeding paragraph/section overlays. O(n) time over a single pass of the input;
O(distinct moves) memory. Weights are accumulated as exact Fractions so the
result is independent of input order. The 100 000-word bound is untested.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
import math

from service.vectors import Level, LevelVector

_AGGREGATE_LEVELS = (Level.BLOCK, Level.SECTION)


@dataclass(frozen=True)
class SentenceLabel:
    node_id: str
    move: str
    confidence: float

    def __post_init__(self):
        for name in ('node_id', 'move'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f'{name} must be a non-empty str')
        conf = self.confidence
        if isinstance(conf, bool) or not isinstance(conf, (int, float)):
            raise ValueError('confidence must be a number')
        conf = float(conf)
        if not math.isfinite(conf) or not 0.0 <= conf <= 1.0:
            raise ValueError('confidence must be finite in [0, 1]')
        object.__setattr__(self, 'confidence', conf)


@dataclass(frozen=True)
class AggregateLabel:
    level: Level
    move: str | None
    confidence: float
    distribution: tuple[tuple[str, float], ...]
    support: int


def _accumulate(labels, weights, counts):
    support = 0
    for label in labels:
        if isinstance(label, LevelVector):
            raise TypeError('LevelVector cannot enter label aggregation (I2)')
        if not isinstance(label, SentenceLabel):
            raise TypeError(f'expected SentenceLabel, got {type(label).__name__}')
        weights[label.move] = weights.get(label.move, Fraction(0)) + Fraction(label.confidence)
        counts[label.move] = counts.get(label.move, 0) + 1
        support += 1
    return support


def _result(level, weights, counts, support):
    if support == 0:
        return AggregateLabel(level, None, 0.0, (), 0)
    total = sum(weights.values(), Fraction(0))
    if total == 0:
        weights = {move: Fraction(n) for move, n in counts.items()}
        total = Fraction(support)
    ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    distribution = tuple((move, float(w / total)) for move, w in ranked)
    move, share = distribution[0]
    return AggregateLabel(level, move, share, distribution, support)


def aggregate(labels: Iterable[SentenceLabel], level: Level) -> AggregateLabel:
    """Confidence-weighted move vote over sentence labels at paragraph/section level."""
    if level not in _AGGREGATE_LEVELS:
        raise ValueError('level must be Level.BLOCK (paragraph) or Level.SECTION')
    weights, counts = {}, {}
    support = _accumulate(labels, weights, counts)
    return _result(level, weights, counts, support)


def aggregate_section(paragraphs: Iterable[Iterable[SentenceLabel]]) -> AggregateLabel:
    """Section label pooled over all sentences of all paragraphs (not a paragraph vote)."""
    weights, counts = {}, {}
    support = 0
    for paragraph in paragraphs:
        if isinstance(paragraph, (LevelVector, SentenceLabel)):
            raise TypeError('aggregate_section expects an iterable of paragraphs')
        support += _accumulate(paragraph, weights, counts)
    return _result(Level.SECTION, weights, counts, support)

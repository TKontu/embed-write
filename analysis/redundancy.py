"""RD-01 fast-layer redundancy candidates: within-level similarity across sections.

Unwired by design until RD-02 (slow-layer recap check) and the G-04 redundancy
overlay consume it. Pure stdlib over service.vectors.

Scale: O(n^2 * d) time per document; memory O(n + limit) with a limit, else
O(n + pairs). Per-document only; no corpus is held. The large-document bound
is untested.
"""

from dataclasses import dataclass
import heapq
import itertools
from numbers import Real
from typing import Iterable

from service.vectors import CrossLevelError, LevelVector, cosine


@dataclass(frozen=True)
class Unit:
    node_id: str
    section_id: str
    index: int
    vector: LevelVector

    def __post_init__(self):
        for name in ('node_id', 'section_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f'{name} must be a non-empty string')
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise ValueError('index must be an int >= 0')
        if not isinstance(self.vector, LevelVector):
            raise TypeError('vector must be a LevelVector')


@dataclass(frozen=True)
class RedundantPair:
    first: str
    second: str
    first_section: str
    second_section: str
    score: float


def redundant_pairs(units: Iterable[Unit], *, threshold: float = 0.9,
                    limit: int | None = None) -> tuple[RedundantPair, ...]:
    """Return cross-section pairs with cosine >= threshold, adjacent indices excluded."""
    if (isinstance(threshold, bool) or not isinstance(threshold, Real)
            or not -1 < threshold <= 1):
        raise ValueError('threshold must be a real number in (-1, 1]')
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                              or limit < 1):
        raise ValueError('limit must be None or an int >= 1')
    items = list(units)
    for unit in items:
        if not isinstance(unit, Unit):
            raise TypeError('units must be Unit instances')
    if len({u.node_id for u in items}) != len(items):
        raise ValueError('duplicate node_id')
    if len({u.index for u in items}) != len(items):
        raise ValueError('duplicate index')
    levels = {u.vector.level for u in items}
    if len(levels) > 1:
        raise CrossLevelError('units must share one level')
    items.sort(key=lambda u: u.index)

    def candidates():
        for a, b in itertools.combinations(items, 2):
            if a.section_id == b.section_id or b.index - a.index == 1:
                continue
            score = cosine(a.vector, b.vector)
            if score >= threshold:
                yield (-score, a.index, b.index), RedundantPair(
                    a.node_id, b.node_id, a.section_id, b.section_id, score)

    key = lambda item: item[0]
    found = (heapq.nsmallest(limit, candidates(), key=key) if limit is not None
             else sorted(candidates(), key=key))
    return tuple(pair for _, pair in found)

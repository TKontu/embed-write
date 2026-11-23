"""Move-transition statistics per section type (SQ-01, I2).

Counts move transitions from labelled section sequences in a single streaming
pass. Pure stdlib; consumes move labels only, never corpus text or vectors.
Each section contributes START->first, consecutive pairs and last->END; an
empty moves tuple contributes START->END.

Unwired by design until SQ-03: the SQ-02/SQ-03 detectors fed by corpus labels
are the production caller; support() exists for SQ-04 thresholds.
O(total moves) time; memory O(section types x distinct transitions + distinct
document ids per transition). The 100 000-word / full-corpus bound is untested.
"""

from collections.abc import Iterable
from dataclasses import dataclass

START = '<start>'
END = '<end>'
_SENTINELS = (START, END)


@dataclass(frozen=True)
class LabelledSection:
    document_id: str
    section_type: str
    moves: tuple[str, ...]

    def __post_init__(self):
        for name in ('document_id', 'section_type'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f'{name} must be a non-empty str')
        if not isinstance(self.moves, tuple):
            raise ValueError('moves must be a tuple of str')
        for move in self.moves:
            if not isinstance(move, str) or not move:
                raise ValueError('each move must be a non-empty str')
            if move in _SENTINELS:
                raise ValueError(f'{move!r} is a reserved sentinel')


class TransitionStats:
    """Transition counts, probabilities and document support per section type."""

    def __init__(self):
        self._counts = {}    # type -> {(prev, next): count}
        self._docs = {}      # type -> {(prev, next): set(document_id)}
        self._out = {}       # type -> {prev: total outgoing}
        self._sections = {}  # type -> section count

    @classmethod
    def from_sections(cls, sections: Iterable[LabelledSection]):
        stats = cls()
        for section in sections:
            if not isinstance(section, LabelledSection):
                raise TypeError('expected LabelledSection, got '
                                f'{type(section).__name__}')
            stats._add(section)
        return stats

    def _add(self, section):
        kind = section.section_type
        counts = self._counts.setdefault(kind, {})
        docs = self._docs.setdefault(kind, {})
        out = self._out.setdefault(kind, {})
        self._sections[kind] = self._sections.get(kind, 0) + 1
        path = (START, *section.moves, END)
        for pair in zip(path, path[1:]):
            counts[pair] = counts.get(pair, 0) + 1
            docs.setdefault(pair, set()).add(section.document_id)
            out[pair[0]] = out.get(pair[0], 0) + 1

    def count(self, section_type, prev, next) -> int:
        return self._counts.get(section_type, {}).get((prev, next), 0)

    def probability(self, section_type, prev, next) -> float:
        total = self._out.get(section_type, {}).get(prev, 0)
        if not total:
            return 0.0
        return self.count(section_type, prev, next) / total

    def support(self, section_type, prev, next) -> int:
        return len(self._docs.get(section_type, {}).get((prev, next), ()))

    def section_count(self, section_type) -> int:
        return self._sections.get(section_type, 0)

    def section_types(self) -> tuple:
        return tuple(sorted(self._sections))

    def transitions(self, section_type) -> tuple:
        counts = self._counts.get(section_type, {})
        docs = self._docs.get(section_type, {})
        rows = [(p, n, c, len(docs[(p, n)])) for (p, n), c in counts.items()]
        rows.sort(key=lambda r: (r[0], -r[2], r[1]))
        return tuple(rows)

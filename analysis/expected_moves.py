"""Expected-move sets per section type (SQ-02, I2).

Classifies each move of a section type by presence rate: the share of that
type's sections containing the move at least once. Built in one streaming
pass over LabelledSection items (analysis.transitions); pure stdlib, move
labels only, never corpus text or vectors.

Roles: EXPECTED when rate >= expected_threshold, OPTIONAL when
optional_threshold <= rate < expected_threshold, RARE below that. Sections
with no moves still count toward section_count.

Unwired by design until SQ-03: the SQ-03 detectors are the production caller.
Memory O(section types x distinct moves + distinct document ids per move).
The full-corpus bound is untested.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from analysis.transitions import LabelledSection

EXPECTED = 'expected'
OPTIONAL = 'optional'
RARE = 'rare'


@dataclass(frozen=True)
class MovePresence:
    move: str
    sections_with: int
    section_count: int
    rate: float
    documents_with: int
    role: str


class ExpectedMoves:
    """Per-section-type move presence rates and roles."""

    def __init__(self, expected_threshold=0.9, optional_threshold=0.1):
        for value in (expected_threshold, optional_threshold):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError('thresholds must be numbers')
        if not 0 < optional_threshold <= expected_threshold <= 1:
            raise ValueError('require 0 < optional_threshold <= '
                             'expected_threshold <= 1')
        self._expected = expected_threshold
        self._optional = optional_threshold
        self._sections = {}  # type -> section count
        self._with = {}      # type -> {move: sections containing it}
        self._docs = {}      # type -> {move: set(document_id)}

    @classmethod
    def from_sections(cls, sections: Iterable[LabelledSection], *,
                      expected_threshold=0.9, optional_threshold=0.1):
        result = cls(expected_threshold, optional_threshold)
        for section in sections:
            if not isinstance(section, LabelledSection):
                raise TypeError('expected LabelledSection, got '
                                f'{type(section).__name__}')
            result._add(section)
        return result

    def _add(self, section):
        kind = section.section_type
        self._sections[kind] = self._sections.get(kind, 0) + 1
        with_ = self._with.setdefault(kind, {})
        docs = self._docs.setdefault(kind, {})
        for move in set(section.moves):
            with_[move] = with_.get(move, 0) + 1
            docs.setdefault(move, set()).add(section.document_id)

    def _role(self, rate):
        if rate >= self._expected:
            return EXPECTED
        if rate >= self._optional:
            return OPTIONAL
        return RARE

    def section_types(self) -> tuple:
        return tuple(sorted(self._sections))

    def section_count(self, section_type) -> int:
        return self._sections.get(section_type, 0)

    def presence(self, section_type, move):
        sections_with = self._with.get(section_type, {}).get(move)
        if sections_with is None:
            return None
        total = self._sections[section_type]
        rate = sections_with / total
        return MovePresence(move, sections_with, total, rate,
                            len(self._docs[section_type][move]),
                            self._role(rate))

    def moves(self, section_type) -> tuple:
        rows = [self.presence(section_type, m)
                for m in self._with.get(section_type, {})]
        rows.sort(key=lambda p: (-p.rate, p.move))
        return tuple(rows)

    def expected(self, section_type) -> tuple:
        return tuple(p.move for p in self.moves(section_type)
                     if p.role == EXPECTED)

    def optional(self, section_type) -> tuple:
        return tuple(p.move for p in self.moves(section_type)
                     if p.role == OPTIONAL)

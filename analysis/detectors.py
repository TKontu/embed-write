"""Sequence detectors over move labels (SQ-03, I2).

Three detectors compare one LabelledSection against corpus models built by
analysis.transitions (TransitionStats) and analysis.expected_moves
(ExpectedMoves):

- missing: an EXPECTED move of the section type is absent;
- foreign: a present move is unseen for the type or has role RARE;
- out_of_order: a transition in (START, non-foreign moves..., END) whose
  probability is below order_threshold.

Every Finding carries its evidence: how often the pattern occurs in the corpus.
Pure stdlib; move labels only. No corpus is held here; per-section cost is
O(moves + expected moves).

Unwired by design until SQ-04: SQ-04 support filtering (and later the
sequence-fit overlay) is the production caller. No support threshold or
suppression is applied here.
"""

from dataclasses import dataclass

from analysis.expected_moves import RARE, ExpectedMoves
from analysis.transitions import END, START, LabelledSection, TransitionStats

MISSING = 'missing'
OUT_OF_ORDER = 'out_of_order'
FOREIGN = 'foreign'
_KIND_ORDER = (MISSING, FOREIGN, OUT_OF_ORDER)


@dataclass(frozen=True)
class Finding:
    kind: str
    section_type: str
    move: str
    position: int | None
    evidence: tuple


def _evidence(**values):
    return tuple(sorted(values.items()))


def _presence_evidence(presence, section_count):
    if presence is None:
        return _evidence(sections_with=0, section_count=section_count,
                         rate=0.0, documents_with=0)
    return _evidence(sections_with=presence.sections_with,
                     section_count=presence.section_count,
                     rate=presence.rate,
                     documents_with=presence.documents_with)


def _sort_key(finding):
    pos = finding.position
    return (_KIND_ORDER.index(finding.kind), pos is None,
            pos if pos is not None else 0, finding.move)


class Detectors:
    """Missing, foreign and out-of-order detectors for labelled sections."""

    def __init__(self, transitions, expected, *, order_threshold=0.05):
        if not isinstance(transitions, TransitionStats):
            raise TypeError('transitions must be TransitionStats')
        if not isinstance(expected, ExpectedMoves):
            raise TypeError('expected must be ExpectedMoves')
        if (isinstance(order_threshold, bool)
                or not isinstance(order_threshold, (int, float))):
            raise ValueError('order_threshold must be a number')
        if not 0 < order_threshold <= 1:
            raise ValueError('require 0 < order_threshold <= 1')
        self._transitions = transitions
        self._expected = expected
        self._threshold = order_threshold

    def _known(self, section):
        if not isinstance(section, LabelledSection):
            raise TypeError('expected LabelledSection, got '
                            f'{type(section).__name__}')
        kind = section.section_type
        return (self._transitions.section_count(kind) > 0
                and self._expected.section_count(kind) > 0)

    def _is_foreign(self, kind, move):
        presence = self._expected.presence(kind, move)
        return presence is None or presence.role == RARE

    def missing(self, section) -> tuple:
        if not self._known(section):
            return ()
        kind = section.section_type
        present = set(section.moves)
        out = [Finding(MISSING, kind, move, None,
                       _presence_evidence(self._expected.presence(kind, move),
                                          self._expected.section_count(kind)))
               for move in self._expected.expected(kind)
               if move not in present]
        return tuple(sorted(out, key=_sort_key))

    def foreign(self, section) -> tuple:
        if not self._known(section):
            return ()
        kind = section.section_type
        total = self._expected.section_count(kind)
        seen = set()
        out = []
        for index, move in enumerate(section.moves):
            if move in seen:
                continue
            seen.add(move)
            presence = self._expected.presence(kind, move)
            if presence is None or presence.role == RARE:
                out.append(Finding(FOREIGN, kind, move, index,
                                   _presence_evidence(presence, total)))
        return tuple(sorted(out, key=_sort_key))

    def out_of_order(self, section) -> tuple:
        if not self._known(section):
            return ()
        kind = section.section_type
        stats = self._transitions
        path = [(START, None)]
        path += [(m, i) for i, m in enumerate(section.moves)
                 if not self._is_foreign(kind, m)]
        path.append((END, len(section.moves)))
        out = []
        for (prev, _), (nxt, pos) in zip(path, path[1:]):
            probability = stats.probability(kind, prev, nxt)
            if probability < self._threshold:
                out.append(Finding(
                    OUT_OF_ORDER, kind, f'{prev}->{nxt}', pos,
                    _evidence(count=stats.count(kind, prev, nxt),
                              probability=probability,
                              support=stats.support(kind, prev, nxt),
                              section_count=stats.section_count(kind))))
        return tuple(sorted(out, key=_sort_key))

    def detect(self, section) -> tuple:
        return self.missing(section) + self.foreign(section) + \
            self.out_of_order(section)

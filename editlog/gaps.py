"""Correction-gap report over the edit log (EL-06).

Measures where experts correct generated text: per move and per
(section_type, move), counts of accept / edit / reject and `revised`
(edit + reject; "corrections" would trip the I8 linter, which bans "correct").
Optionally, with an injected ``features`` callable
(``text -> iterable[str]``; no register-feature extractor exists yet),
counts register features experts added or removed in edit entries.

Unwired by design: the expert-facing view that shows this report is a later
row. Stdlib only, local only (I9). The store is streamed once via
``iter_entries()``; memory is bounded by distinct moves/features, not entries.
Field names are neutral counts, never quality judgements (I8).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

DISPLAY_LABELS = {
    'total': 'Entries',
    'accept': 'Accepted',
    'edit': 'Edited',
    'reject': 'Rejected',
    'revised': 'Edited or rejected',
    'added': 'Feature added by expert',
    'removed': 'Feature removed by expert',
}


@dataclass(frozen=True)
class MoveCount:
    move: str
    total: int
    accept: int
    edit: int
    reject: int
    revised: int


@dataclass(frozen=True)
class SectionMoveCount:
    section_type: str
    move: str
    total: int
    accept: int
    edit: int
    reject: int
    revised: int


@dataclass(frozen=True)
class FeatureCount:
    feature: str
    added: int
    removed: int


@dataclass(frozen=True)
class GapReport:
    moves: tuple
    section_moves: tuple
    features: tuple


def _row(cls, key, c):
    return cls(*key, total=c['accept'] + c['edit'] + c['reject'],
               accept=c['accept'], edit=c['edit'], reject=c['reject'],
               revised=c['edit'] + c['reject'])


def gap_report(store, features=None):
    """Stream ``store.iter_entries()`` once and return a frozen GapReport."""
    by_move = defaultdict(Counter)
    by_section = defaultdict(Counter)
    added, removed = Counter(), Counter()
    for _id, entry in store.iter_entries():
        by_move[(entry.move,)][entry.action] += 1
        by_section[(entry.section_type, entry.move)][entry.action] += 1
        if features is not None and entry.action == 'edit':
            before = set(features(entry.candidate))
            after = set(features(entry.final_text))
            added.update(after - before)
            removed.update(before - after)
    moves = sorted((_row(MoveCount, k, c) for k, c in by_move.items()),
                   key=lambda r: (-r.revised, r.move))
    sections = sorted(
        (_row(SectionMoveCount, k, c) for k, c in by_section.items()),
        key=lambda r: (-r.revised, r.move, r.section_type))
    feats = sorted(
        (FeatureCount(f, added[f], removed[f]) for f in set(added) | set(removed)),
        key=lambda r: (-(r.added + r.removed), r.feature))
    return GapReport(tuple(moves), tuple(sections), tuple(feats))

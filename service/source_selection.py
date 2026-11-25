"""Source selection per planned move (todo-07 AD-02).

Architecture §5.11: for each move, retrieve the relevant source items (§5.1 first-class objects).
Moves are plain caller-supplied ``MoveRequest`` rows; the pattern model (AD-01, G-01) does not exist
yet. Pure stdlib, local only (I9).

``select_sources`` consumes the items in a single pass and keeps, per move, a top-k heap of
(score, position, id) plus the list of item ids; item contents are not retained. Memory is
O(len(requests) * k) heap entries plus the id list; time is O(len(requests) * items) score calls.

``lexical_score`` is the deterministic offline default scorer until an embedding scorer is chosen
(G-03).

Unwired by design until AD-03 (per-move generation), which consumes ``MoveSelection`` to choose
items and the ids it links sentences to; AD-04 ``check_grounding`` verifies those links.
"""

from __future__ import annotations

import heapq
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from service.source_items import SourceItem

_TOKEN = re.compile(r"\w+")


@dataclass(frozen=True)
class MoveRequest:
    move: str
    query: str


@dataclass(frozen=True)
class Selected:
    item_id: str
    score: float


@dataclass(frozen=True)
class MoveSelection:
    move: str
    selected: tuple[Selected, ...]


@dataclass(frozen=True)
class SelectionReport:
    moves: tuple[MoveSelection, ...]
    unused_ids: tuple[str, ...]

    @property
    def empty_moves(self) -> tuple[str, ...]:
        return tuple(m.move for m in self.moves if not m.selected)


def select_sources(
    requests: Sequence[MoveRequest],
    items: Iterable[SourceItem],
    score: Callable[[str, SourceItem], float],
    *,
    k: int = 5,
    min_score: float = 0.0,
) -> SelectionReport:
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    requests = list(requests)
    seen_moves: set[str] = set()
    for req in requests:
        if not isinstance(req, MoveRequest):
            raise TypeError(f"request must be MoveRequest, got {type(req).__name__}")
        if not isinstance(req.move, str) or not req.move.strip():
            raise ValueError("move name must be a non-empty string")
        if not isinstance(req.query, str) or not req.query.strip():
            raise ValueError(f"move {req.move!r}: query must be a non-empty string")
        if req.move in seen_moves:
            raise ValueError(f"duplicate move name {req.move!r}")
        seen_moves.add(req.move)

    # Min-heap per move of (score, -position, id): the root is the weakest kept entry, and among
    # equal scores the latest item is evicted first, so ties keep first appearance.
    heaps: list[list[tuple[float, int, str]]] = [[] for _ in requests]
    ids: list[str] = []
    id_set: set[str] = set()
    for pos, it in enumerate(items):
        if not isinstance(it, SourceItem):
            raise TypeError(f"item must be SourceItem, got {type(it).__name__}")
        if it.id in id_set:
            raise ValueError(f"duplicate item id {it.id!r}")
        id_set.add(it.id)
        ids.append(it.id)
        for req, heap in zip(requests, heaps):
            s = float(score(req.query, it))
            if not math.isfinite(s):
                raise ValueError(f"non-finite score {s!r} for move {req.move!r}, item {it.id!r}")
            if s < min_score:
                continue
            entry = (s, -pos, it.id)
            if len(heap) < k:
                heapq.heappush(heap, entry)
            elif entry > heap[0]:
                heapq.heapreplace(heap, entry)

    moves = []
    used: set[str] = set()
    for req, heap in zip(requests, heaps):
        ordered = sorted(heap, key=lambda e: (-e[0], -e[1]))
        used.update(e[2] for e in ordered)
        moves.append(MoveSelection(req.move, tuple(Selected(e[2], e[0]) for e in ordered)))
    return SelectionReport(tuple(moves), tuple(i for i in ids if i not in used))


def lexical_score(query: str, item: SourceItem) -> float:
    q = set(_TOKEN.findall(query.lower()))
    if not q:
        return 0.0
    c = set(_TOKEN.findall(item.content.lower()))
    return len(q & c) / len(q)

"""Perturbation generator for G-05 (SQ-05, G-05.1).

Deterministically perturbs LabelledSection move sequences -- delete a move,
swap two distinct moves, insert a foreign move -- and records the ground truth
of each change so detector precision/recall can later be measured (G-05.2).
Pure stdlib; consumes move labels only, never corpus text or vectors.

Unwired by design until the G-05 runner (G-05.1/G-05.2, docs/todo-01).
perturb() streams its input: O(total moves x kinds) time, memory O(one
section + foreign_moves).
"""

import random
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

from analysis.transitions import END, START, LabelledSection

DELETE = 'delete'
SWAP = 'swap'
INSERT = 'insert'
KINDS = (DELETE, SWAP, INSERT)
_SENTINELS = (START, END)


@dataclass(frozen=True)
class Perturbation:
    """Ground truth for one perturbation.

    delete: positions=(index,), move=removed move.
    swap:   positions=(i, j) with i < j, move=None.
    insert: positions=(index,) in the perturbed sequence, move=foreign move.
    """
    document_id: str
    section_type: str
    kind: str
    original: tuple
    perturbed: tuple
    positions: tuple
    move: str | None


def _check_section(section):
    if not isinstance(section, LabelledSection):
        raise TypeError('expected LabelledSection, got '
                        f'{type(section).__name__}')


def _check_index(index, upper, name='index'):
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError(f'{name} must be an int')
    if not 0 <= index < upper:
        raise ValueError(f'{name} {index} out of range [0, {upper})')


def _result(section, kind, moves, positions, move):
    perturbed = replace(section, moves=tuple(moves))
    return perturbed, Perturbation(section.document_id, section.section_type,
                                   kind, section.moves, perturbed.moves,
                                   tuple(positions), move)


def delete_move(section, index):
    _check_section(section)
    _check_index(index, len(section.moves))
    moves = list(section.moves)
    removed = moves.pop(index)
    return _result(section, DELETE, moves, (index,), removed)


def swap_moves(section, i, j):
    _check_section(section)
    _check_index(i, len(section.moves), 'i')
    _check_index(j, len(section.moves), 'j')
    moves = list(section.moves)
    if moves[i] == moves[j]:
        raise ValueError('swap requires two distinct moves')
    moves[i], moves[j] = moves[j], moves[i]
    return _result(section, SWAP, moves, (min(i, j), max(i, j)), None)


def insert_move(section, index, move):
    _check_section(section)
    _check_index(index, len(section.moves) + 1)
    if not isinstance(move, str) or not move:
        raise ValueError('move must be a non-empty str')
    if move in _SENTINELS:
        raise ValueError(f'{move!r} is a reserved sentinel')
    if move in section.moves:
        raise ValueError(f'{move!r} already in section')
    moves = list(section.moves)
    moves.insert(index, move)
    return _result(section, INSERT, moves, (index,), move)


def _one(section, kind, foreign, rng):
    moves = section.moves
    n = len(moves)
    if kind == DELETE:
        if not n:
            return None
        return delete_move(section, rng.randrange(n))
    if kind == SWAP:
        if len(set(moves)) < 2:
            return None
        i = rng.randrange(n)
        others = [j for j in range(n) if moves[j] != moves[i]]
        j = others[rng.randrange(len(others))]
        return swap_moves(section, i, j)
    present = set(moves)
    candidates = [m for m in foreign if m not in present]
    if not candidates:
        return None
    move = candidates[rng.randrange(len(candidates))]
    return insert_move(section, rng.randrange(n + 1), move)


def perturb(sections: Iterable[LabelledSection], *, kinds=KINDS,
            foreign_moves: Sequence[str],
            seed: int) -> Iterator[tuple[LabelledSection, Perturbation]]:
    """Yield one perturbation per (section, applicable kind), seeded once."""
    kinds = tuple(kinds)
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError(f'unknown kind {kind!r}')
    if isinstance(foreign_moves, str):
        raise ValueError('foreign_moves must be a sequence of str')
    foreign = []
    for move in foreign_moves:
        if not isinstance(move, str) or not move or move in _SENTINELS:
            raise ValueError(f'invalid foreign move {move!r}')
        if move not in foreign:
            foreign.append(move)
    return _generate(sections, kinds, tuple(foreign), random.Random(seed))


def _generate(sections, kinds, foreign, rng):
    for section in sections:
        _check_section(section)
        for kind in kinds:
            out = _one(section, kind, foreign, rng)
            if out is not None:
                yield out


def log_record(p: Perturbation) -> dict:
    return {'document_id': p.document_id, 'section_type': p.section_type,
            'kind': p.kind, 'original': list(p.original),
            'perturbed': list(p.perturbed), 'positions': list(p.positions),
            'move': p.move}

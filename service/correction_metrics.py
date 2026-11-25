"""AD-10 correction metrics: share of machine sentences the expert edited, by move.

Pure library over AD-06 draft blocks; local only (I9). Unwired by design until
AD-08 (review flow) calls it after expert review. Memory is O(draft size).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from service.draft_assembly import DraftBlock
from service.segment import segment_sentences


@dataclass(frozen=True)
class MoveCorrection:
    move: str
    machine_sentences: int
    edited_sentences: int
    share_edited: float


@dataclass(frozen=True)
class DraftCorrection:
    by_move: tuple[MoveCorrection, ...]
    machine_sentences: int
    edited_sentences: int
    share_edited: float


def _norm(sentence: str) -> str:
    return " ".join(sentence.split())


def _share(edited: int, machine: int) -> float:
    return edited / machine if machine else 0.0


def correction_metrics(blocks: Sequence[DraftBlock], final_texts: Sequence[str]) -> DraftCorrection:
    """Count machine sentences absent (multiset, whitespace-normalized) from each final text."""
    if len(blocks) != len(final_texts):
        raise ValueError(f"{len(blocks)} blocks but {len(final_texts)} final texts")
    counts: dict[str, list[int]] = {}
    for block, final in zip(blocks, final_texts):
        remaining = Counter(_norm(s) for s in segment_sentences(final))
        machine = edited = 0
        for sentence in segment_sentences(block.text):
            machine += 1
            key = _norm(sentence)
            if remaining[key] > 0:
                remaining[key] -= 1
            else:
                edited += 1
        totals = counts.setdefault(block.move, [0, 0])
        totals[0] += machine
        totals[1] += edited
    by_move = tuple(MoveCorrection(m, n, e, _share(e, n)) for m, (n, e) in counts.items())
    machine_total = sum(m.machine_sentences for m in by_move)
    edited_total = sum(m.edited_sentences for m in by_move)
    return DraftCorrection(by_move, machine_total, edited_total, _share(edited_total, machine_total))

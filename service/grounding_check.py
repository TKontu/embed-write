"""Grounding check (AD-04): every generated factual sentence links to a source item.

``check_grounding`` takes generated sentences, each carrying the source item ids the generator
linked it to (docs/architecture.md section 5.1, span-to-source links), and the selected source
items. Every sentence appears in the report in input order; nothing is dropped. A claim with no
link to an existing item is flagged ("unlinked" when it has no ids, "unknown-source" when all its
ids are absent), never silently kept. Ids absent from the items are always reported. This is a
link check only: semantic support is VF-02/G-08 and number matching is AD-05. Runs locally (I9).

Unwired by design until AD-03 (per-move generation, the producer of linked sentences) and AD-08
(review flow, which shows flagged sentences) call it. Items are consumed in one pass into a set of
ids (bounded by AD-02 source selection); memory is linear in sentences plus items.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from service.segment import segment_sentences
from service.source_items import SourceItem


@dataclass(frozen=True)
class GeneratedSentence:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class SentenceGrounding:
    index: int
    text: str
    linked_ids: tuple[str, ...]
    unknown_ids: tuple[str, ...]
    flagged: bool
    reason: str | None


@dataclass(frozen=True)
class GroundingReport:
    sentences: tuple[SentenceGrounding, ...]
    flagged_count: int

    @property
    def flagged(self) -> tuple[SentenceGrounding, ...]:
        return tuple(row for row in self.sentences if row.flagged)


def check_grounding(
    sentences: Iterable[GeneratedSentence],
    items: Iterable[SourceItem],
    is_claim: Callable[[str], bool] | None = None,
) -> GroundingReport:
    known = {item.id for item in items}
    rows = []
    for index, sentence in enumerate(sentences):
        if not isinstance(sentence, GeneratedSentence):
            raise TypeError(f"sentence {index}: expected GeneratedSentence")
        if not isinstance(sentence.text, str) or not sentence.text.strip():
            raise ValueError(f"sentence {index}: text must be non-empty")
        unique = tuple(dict.fromkeys(sentence.source_ids))
        linked = tuple(i for i in unique if i in known)
        unknown = tuple(i for i in unique if i not in known)
        reason = None
        if (is_claim is None or is_claim(sentence.text)) and not linked:
            reason = "unknown-source" if unknown else "unlinked"
        rows.append(
            SentenceGrounding(index, sentence.text, linked, unknown, reason is not None, reason)
        )
    return GroundingReport(tuple(rows), sum(row.flagged for row in rows))


def sentences_from_text(text: str, source_ids: Sequence[str]) -> tuple[GeneratedSentence, ...]:
    """Split a block generated from one source set; every sentence carries the same ids."""
    ids = tuple(source_ids)
    return tuple(GeneratedSentence(s, ids) for s in segment_sentences(text))

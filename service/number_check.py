"""Number check (AD-05): every number and unit in a draft traced to a source item.

``check_numbers`` takes draft text and a sequence of ``(source_id, text)`` source items and reports,
for each distinct ``num:`` token of the draft (tokens from ``support_check.extract_support``), the
ids of the source items whose text contains the same token, plus the draft tokens no source
contains. Per docs/architecture.md (automatic drafting), an untraceable claim is flagged, never
silently kept; this module only reports -- no score, no threshold, no rewriting.

Presence semantics: a token counts as matched if it occurs at least once in some source,
regardless of how often it appears in the draft (``3 h`` twice in the draft, once in a source,
is matched). ``link:`` and ``cite:`` tokens are ignored; numbers inside URLs are therefore not
counted. Values and units must match literally ("12 kg" vs "15 kg", "5 km" vs "5 m" are
unmatched).

``check_quantities`` (quantity level) compares each draft quantity occurrence (SR-04
``extract_quantities``) with quantities extracted from SR-02 ``SourceItem.content``: same unit
(both None is same; a unitless item quantity takes the item's unit when ``item.units`` has exactly
one entry) and, for a value, an equal value (``math.isclose`` rel 1e-9); for a range/tolerance,
equal low and high against an item range/tolerance. Items are streamed in one pass.

Unwired by design until AD-04/AD-06 call it. Residual: ``check_quantities`` is linear in draft
quantities x item quantities per item. Residuals: paraphrased numbers ("five" vs "5") and
unit conversion are not handled. Linear in total text length; holds one draft and its sources.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from service.quantities import Quantity, extract_quantities
from service.source_items import SourceItem
from service.support_check import extract_support


@dataclass(frozen=True)
class NumberCheck:
    """``matches``: draft num token -> matching source ids (draft order); ``unmatched``: tokens with none."""

    matches: Mapping[str, tuple]
    unmatched: tuple

    @property
    def all_matched(self) -> bool:
        return not self.unmatched


def _num_tokens(text: str) -> list:
    return [t for t in extract_support(text) if t.startswith("num:")]


def check_numbers(draft: str, sources: Iterable[tuple]) -> NumberCheck:
    """Report which source ids contain each draft number token; reporting only."""
    draft_tokens = _num_tokens(draft)
    matches = {token: [] for token in draft_tokens}
    for source_id, text in sources:
        for token in set(_num_tokens(text)):
            if token in matches:
                matches[token].append(source_id)
    frozen = {token: tuple(ids) for token, ids in matches.items()}
    return NumberCheck(matches=frozen, unmatched=tuple(t for t, ids in frozen.items() if not ids))


@dataclass(frozen=True)
class QuantityMatch:
    """One draft quantity occurrence and the ids of matching source items (item order)."""

    quantity: Quantity
    item_ids: tuple[str, ...]


@dataclass(frozen=True)
class QuantityCheck:
    """``matches``: one entry per draft quantity occurrence, in draft order."""

    matches: tuple[QuantityMatch, ...]

    @property
    def unmatched(self) -> tuple[Quantity, ...]:
        return tuple(m.quantity for m in self.matches if not m.item_ids)

    @property
    def all_matched(self) -> bool:
        return not self.unmatched


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9)


def _same(draft: Quantity, src: Quantity, src_unit: str | None) -> bool:
    if draft.unit != src_unit:
        return False
    if draft.kind == "value":
        return src.kind == "value" and _close(draft.value, src.value)
    return src.kind != "value" and _close(draft.low, src.low) and _close(draft.high, src.high)


def check_quantities(draft: str, items: Iterable[SourceItem]) -> QuantityCheck:
    """Report which source items hold each draft quantity; reporting only."""
    draft_qs = extract_quantities(draft)
    ids: list[list[str]] = [[] for _ in draft_qs]
    for item in items:
        if not draft_qs:
            break
        fallback = item.units[0] if len(item.units) == 1 else None
        item_qs = [(q, q.unit if q.unit is not None else fallback) for q in extract_quantities(item.content)]
        for i, dq in enumerate(draft_qs):
            if any(_same(dq, q, unit) for q, unit in item_qs):
                ids[i].append(item.id)
    return QuantityCheck(matches=tuple(QuantityMatch(q, tuple(x)) for q, x in zip(draft_qs, ids)))

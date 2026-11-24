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

Unwired by design until AD-04/AD-06 call it. Residuals: paraphrased numbers ("five" vs "5") and
unit conversion are not handled. Linear in total text length; holds one draft and its sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

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

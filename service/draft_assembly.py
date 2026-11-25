"""Draft assembly (AD-06): per-move machine text into one Markdown document.

``assemble_draft`` takes ``(heading, [(move, text), ...])`` sections, already generated, and
returns the Markdown document (``## heading`` then each block as its own paragraph, blank line
between elements, single trailing newline) plus one ``DraftBlock`` per block carrying
``provenance="machine"``. Per docs/architecture.md section 5.2 the Markdown is the document and node
metadata such as provenance lives beside it, never inside the text. The draft status is always
``"draft"`` (I5); this module never promotes it. Runs locally only (I9).

When ``items`` is given, ``check_quantities`` (AD-05) runs per block so untraceable numbers are
flagged, never silently kept. ``items`` is a Sequence because it is re-iterated per block; the
caller holds the selected items and AD-02 source selection bounds their number.

Unwired by design until AD-03 (generation, the producer) and AD-08 (review flow, the consumer)
call it. Sections are consumed in one pass; memory is O(draft size). Residual: quantity checking
costs blocks x item quantities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from service.number_check import QuantityCheck, check_quantities
from service.source_items import SourceItem

_HEADING_LINE = re.compile(r"^#", re.MULTILINE)


@dataclass(frozen=True)
class DraftBlock:
    section: str
    move: str
    text: str
    provenance: str


@dataclass(frozen=True)
class AssembledDraft:
    markdown: str
    blocks: tuple[DraftBlock, ...]
    status: str
    quantity_checks: tuple[QuantityCheck, ...] | None


def assemble_draft(
    sections: Iterable[tuple[str, Iterable[tuple[str, str]]]],
    items: Sequence[SourceItem] | None = None,
) -> AssembledDraft:
    parts: list[str] = []
    blocks: list[DraftBlock] = []
    for heading, moves in sections:
        if not heading or not heading.strip():
            raise ValueError("section heading is empty")
        if "\n" in heading or "\r" in heading:
            raise ValueError(f"section heading contains a newline: {heading!r}")
        heading = heading.strip()
        parts.append(f"## {heading}")
        count = 0
        for move, text in moves:
            text = (text or "").strip()
            if not text:
                raise ValueError(f"empty block text in section {heading!r}, move {move!r}")
            if _HEADING_LINE.search(text):
                raise ValueError(f"block text contains a Markdown heading line: {heading!r}/{move!r}")
            parts.append(text)
            blocks.append(DraftBlock(section=heading, move=move, text=text, provenance="machine"))
            count += 1
        if not count:
            raise ValueError(f"section {heading!r} has no blocks")
    checks = None
    if items is not None:
        checks = tuple(check_quantities(b.text, items) for b in blocks)
    return AssembledDraft(
        markdown="\n\n".join(parts) + "\n" if parts else "",
        blocks=tuple(blocks),
        status="draft",
        quantity_checks=checks,
    )

"""GE-02 exemplar conditioning from a caller-supplied stream.

Unwired by design until the GE-03/GE-04 proposal flow. No store access,
ranking, corpus loading or model calls. Selection retains at most ``limit``
references in a single lazy pass; rendering uses space proportional to the
context and selected text. Individual text sizes are caller-owned and uncapped.
"""

from dataclasses import asdict, dataclass
import json
from typing import Iterable

from generation.context import GenerationContext


@dataclass(frozen=True)
class Exemplar:
    id: str
    document_id: str
    section_type: str
    move: str
    text: str

    def __post_init__(self):
        if not all(isinstance(value, str) for value in
                   (self.id, self.document_id, self.section_type, self.move, self.text)):
            raise ValueError('exemplar fields must be strings')
        if not self.id:
            raise ValueError('exemplar id must be non-empty')


def select_exemplars(candidates: Iterable[Exemplar], *, current_document_id: str,
                     section_type: str, move: str, limit: int,
                     max_per_document: int | None = None) -> tuple[Exemplar, ...]:
    """Select exact label matches outside the current document, in stream order.

    Stop immediately at the limit; zero does not even request an iterator.
    ``max_per_document``, when not ``None``, skips any candidate whose document
    already holds that many selections (skipped, never deferred); it keeps one
    count per selected document, so memory stays O(limit).
    IDs are caller-supplied stable passage identifiers for GenerationRunRecord.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError('limit must be a nonnegative integer')
    if max_per_document is not None and (type(max_per_document) is not int
                                         or max_per_document < 1):
        raise ValueError('max_per_document must be a positive integer or None')
    if limit == 0:
        return ()
    selected = []
    per_document: dict[str, int] = {}
    for candidate in candidates:
        if (candidate.document_id != current_document_id
                and candidate.section_type == section_type and candidate.move == move):
            if max_per_document is not None:
                count = per_document.get(candidate.document_id, 0)
                if count >= max_per_document:
                    continue
                per_document[candidate.document_id] = count + 1
            selected.append(candidate)
            if len(selected) == limit:
                break
    return tuple(selected)


def render_prompt(context: GenerationContext, candidates: Iterable[Exemplar], *,
                  current_document_id: str, section_type: str, limit: int,
                  max_per_document: int | None = None) -> tuple[str, tuple[str, ...]]:
    """Return the unchanged GE-01 prompt plus JSON examples and ordered IDs.

    The move comes from the selected context passage; section type and document
    identity must be supplied by its caller because GE-01 does not carry them.
    ``max_per_document`` is forwarded to :func:`select_exemplars` unchanged.
    """
    selected = select_exemplars(candidates, current_document_id=current_document_id,
                                section_type=section_type, move=context.passage.move,
                                limit=limit, max_per_document=max_per_document)
    examples = json.dumps([asdict(candidate) for candidate in selected],
                          ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return (context.render_prompt() + '\nExemplars:\n' + examples,
            tuple(candidate.id for candidate in selected))

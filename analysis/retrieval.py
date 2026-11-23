"""SP-02 fast layer: same-level candidate evidence retrieval by cosine.

unwired by design until SP-01 claims are embedded via EM-02/SV-02 and SP-03 consumes the candidates
Ranks the document's other sentences and linked source items for each claim and keeps the top k;
no entailment, signal emission, embedding, ANN index or model is involved.
Residuals: Recall@5 (G-07) is not measured; scores are raw clipped cosine, not calibrated;
the corpus-scale bound is untested (synthetic vectors only).
Scale: one pass over evidence, time O(claims * evidence * d), memory O(claims * k + evidence ids).
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Iterable, Mapping

from analysis.support_signals import SupportLink
from service.vectors import CrossLevelError, LevelVector, cosine


def _require_id(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{name} must be a non-empty string')


@dataclass(frozen=True)
class EvidenceItem:
    node_id: str
    vector: LevelVector
    source: str  # "document" for the document's own sentences, else the linked source item id

    def __post_init__(self) -> None:
        _require_id('node_id', self.node_id)
        _require_id('source', self.source)
        if not isinstance(self.vector, LevelVector):
            raise TypeError('vector must be a LevelVector')


@dataclass(frozen=True)
class Candidate:
    claim_id: str
    evidence_id: str
    source: str
    score: float
    rank: int


def retrieve_candidates(claims: Mapping[str, LevelVector],
                        evidence: Iterable[EvidenceItem], *,
                        k: int = 5) -> dict[str, list[Candidate]]:
    """Return the top-k same-level evidence per claim, ranked by cosine (ties: input order)."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError('k must be an int >= 1')
    level = None

    def check_level(vector: LevelVector) -> None:
        nonlocal level
        if level is None:
            level = vector.level
        elif vector.level is not level:
            raise CrossLevelError(f'Cannot compare {level.name} with {vector.level.name}')

    for claim_id, vector in claims.items():
        _require_id('claim id', claim_id)
        if not isinstance(vector, LevelVector):
            raise TypeError('claim vector must be a LevelVector')
        check_level(vector)

    heaps: dict[str, list[tuple[float, int, EvidenceItem]]] = {c: [] for c in claims}
    seen: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, EvidenceItem):
            raise TypeError('evidence must be EvidenceItem')
        if item.node_id in seen:
            raise ValueError(f'duplicate evidence node_id: {item.node_id}')
        seen.add(item.node_id)
        check_level(item.vector)
        for claim_id, vector in claims.items():
            if claim_id == item.node_id:
                continue
            # Min-heap root is the weakest kept entry: lowest score, then latest input.
            entry = (cosine(vector, item.vector), -index, item)
            heap = heaps[claim_id]
            if len(heap) < k:
                heapq.heappush(heap, entry)
            elif entry[:2] > heap[0][:2]:
                heapq.heapreplace(heap, entry)

    result: dict[str, list[Candidate]] = {}
    for claim_id, heap in heaps.items():
        ordered = sorted(heap, key=lambda e: (-e[0], -e[1]))
        result[claim_id] = [
            Candidate(claim_id, item.node_id, item.source, min(1.0, max(0.0, score)), rank)
            for rank, (score, _, item) in enumerate(ordered, start=1)]
    return result


def to_support_links(candidates: Mapping[str, list[Candidate]]) -> list[SupportLink]:
    """Flatten candidates to SupportLinks in claim then rank order."""
    return [SupportLink(c.claim_id, c.evidence_id, c.score)
            for claim_list in candidates.values()
            for c in sorted(claim_list, key=lambda c: c.rank)]

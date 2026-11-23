"""SP-05 support signals.

unwired by design until SP-02/SP-03 produce a SupportMap; flag stays off until G-07 passes
Residuals: candidate scores are supplied, not calibrated or checked for entailment;
no retrieval, claim identification, model or private-corpus validation is performed.
Processing is O(claims + evidence + links) time and memory for one document's map,
with one scan of links per public call and no corpus loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from analysis.signal_gates import SignalFlag
from analysis.signals import Signal


@dataclass(frozen=True)
class SupportLink:
    claim_id: str
    evidence_id: str
    score: float

    def __post_init__(self) -> None:
        if (isinstance(self.score, bool)
                or not isinstance(self.score, (int, float))
                or not 0 <= self.score <= 1):
            raise ValueError('score must be finite and in [0, 1]')


@dataclass(frozen=True)
class SupportMap:
    level: str
    claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    links: tuple[SupportLink, ...]

    def __post_init__(self) -> None:
        claims, evidence = set(self.claim_ids), set(self.evidence_ids)
        if len(claims) != len(self.claim_ids) or len(evidence) != len(self.evidence_ids):
            raise ValueError('duplicate ids within claims or evidence')
        for link in self.links:
            if link.claim_id not in claims or link.evidence_id not in evidence:
                raise ValueError('link references an unknown id')


def _validate(threshold: float, computed_at: str) -> None:
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not 0 < threshold <= 1):
        raise ValueError('threshold must be a number in (0, 1]')
    if not isinstance(computed_at, str) or not computed_at.strip():
        raise ValueError('computed_at must be a non-empty string')


def _best_scores(support_map: SupportMap) -> tuple[dict[str, float], dict[str, float]]:
    claims: dict[str, float] = {}
    evidence: dict[str, float] = {}
    for link in support_map.links:
        score = float(link.score)
        claims[link.claim_id] = max(claims.get(link.claim_id, 0.0), score)
        evidence[link.evidence_id] = max(evidence.get(link.evidence_id, 0.0), score)
    return claims, evidence


def _signals(ids: tuple[str, ...], best: dict[str, float], level: str,
             status: str, method: str, threshold: float, computed_at: str) -> list[Signal]:
    result = []
    for node_id in ids:
        score = best.get(node_id)
        if score is None or score < threshold:
            result.append(Signal(
                node_id=node_id, level=level, kind='support',
                value={'status': status, 'best_score': score},
                confidence=1.0 if score is None else 1.0 - score,
                method_ref=f'support_signals.{method}@threshold={float(threshold)}',
                layer='provisional', computed_at=computed_at,
            ))
    return result


def unsupported_claims(support_map: SupportMap, threshold: float = 0.5, *,
                       computed_at: str) -> list[Signal]:
    """Return claims whose best candidate falls below the inclusive support cutoff."""
    _validate(threshold, computed_at)
    claims, _ = _best_scores(support_map)
    return _signals(support_map.claim_ids, claims, support_map.level,
                    'unsupported', 'unsupported_claims', threshold, computed_at)


def unused_evidence(support_map: SupportMap, threshold: float = 0.5, *,
                    computed_at: str) -> list[Signal]:
    """Return evidence with no candidate link meeting the support cutoff."""
    _validate(threshold, computed_at)
    _, evidence = _best_scores(support_map)
    return _signals(support_map.evidence_ids, evidence, support_map.level,
                    'evidence_unused', 'unused_evidence', threshold, computed_at)


def emit_support_signals(support_map: SupportMap, *, computed_at: str,
                         flags: Mapping[str, SignalFlag],
                         threshold: float = 0.5) -> list[Signal]:
    """Emit claims first, then evidence, only when the support flag is enabled."""
    _validate(threshold, computed_at)
    flag = flags.get('support')
    if flag is None or not flag.enabled:
        return []
    claims, evidence = _best_scores(support_map)
    return (
        _signals(support_map.claim_ids, claims, support_map.level,
                 'unsupported', 'unsupported_claims', threshold, computed_at)
        + _signals(support_map.evidence_ids, evidence, support_map.level,
                   'evidence_unused', 'unused_evidence', threshold, computed_at)
    )

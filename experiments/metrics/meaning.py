"""G-08 meaning-preservation scorer: offline arms, scoring and threshold calibration.

Unwired by design until the G-08 gate runner (G-08.2/G-08.3). Convention: an arm maps
(original, candidate) to a score in [0, 1], 1 = meaning preserved. A pair is flagged
"not preserved" when its score is below the threshold; the silent filter drops flagged pairs.
Only the number-and-unit arm lives here; entailment and AlignScore arms need local models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from service.support_check import support_diff

Arm = Callable[[str, str], float]

_Z95 = 1.959963984540054  # ST-02: Wilson 95% (no shared helper in experiments/metrics)


@dataclass(frozen=True)
class RewritePair:
    pair_id: str
    original: str
    candidate: str
    preserved: bool


@dataclass(frozen=True)
class Rate:
    value: float | None
    n: int
    interval: tuple[float, float] | None


@dataclass(frozen=True)
class ScoreResult:
    threshold: float
    balanced_accuracy: float | None
    tpr: Rate  # preserved pairs kept (score >= threshold)
    tnr: Rate  # not-preserved pairs flagged (score < threshold)
    n: int


@dataclass(frozen=True)
class Calibration:
    threshold: float
    precision: float
    n_flagged: int
    n: int


def wilson(successes: int, n: int) -> tuple[float, float] | None:
    if not n:
        return None
    p = successes / n
    denom = 1 + _Z95 ** 2 / n
    centre = (p + _Z95 ** 2 / (2 * n)) / denom
    half = _Z95 * math.sqrt(p * (1 - p) / n + _Z95 ** 2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate(successes: int, n: int) -> Rate:
    return Rate(successes / n if n else None, n, wilson(successes, n))


def number_unit_arm(original: str, candidate: str) -> float:
    """1.0 when numbers, units, citations and links are unchanged, else 0.0."""
    return 1.0 if support_diff(original, candidate).preserved else 0.0


def _scores(pairs: Iterable[RewritePair], arm: Arm) -> list[tuple[float, bool]]:
    out = []
    for p in pairs:
        s = float(arm(p.original, p.candidate))
        if not 0.0 <= s <= 1.0:  # also rejects NaN
            raise ValueError(f"arm score {s!r} outside [0, 1] for pair {p.pair_id!r}")
        out.append((s, p.preserved))
    if not out:
        raise ValueError("no pairs")
    return out


def _score_list(scored: list[tuple[float, bool]], threshold: float) -> ScoreResult:
    pos = [s for s, keep in scored if keep]
    neg = [s for s, keep in scored if not keep]
    tpr = _rate(sum(s >= threshold for s in pos), len(pos))
    tnr = _rate(sum(s < threshold for s in neg), len(neg))
    ba = (tpr.value + tnr.value) / 2 if pos and neg else None
    return ScoreResult(threshold, ba, tpr, tnr, len(scored))


def score(pairs: Sequence[RewritePair], arm: Arm, threshold: float) -> ScoreResult:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must lie in [0, 1]")
    return _score_list(_scores(pairs, arm), threshold)


def calibrate(pairs: Sequence[RewritePair], arm: Arm,
              target_precision: float = 0.95) -> Calibration | None:
    """Lowest threshold whose not-preserved flags reach ``target_precision``, else None.

    Candidate thresholds are the distinct scores plus 1.0; thresholds that flag nothing
    have undefined precision and are skipped.
    """
    if not 0.0 < target_precision <= 1.0:
        raise ValueError("target_precision must lie in (0, 1]")
    scored = _scores(pairs, arm)
    for t in sorted({s for s, _ in scored} | {1.0}):
        flagged = [keep for s, keep in scored if s < t]
        if not flagged:
            continue
        precision = sum(not k for k in flagged) / len(flagged)
        if precision >= target_precision:
            return Calibration(t, precision, len(flagged), len(scored))
    return None


def combine(arms: Sequence[Arm], weights: Sequence[float]) -> Arm:
    """Weighted-mean arm; weights must be finite, non-negative and sum > 0."""
    arms, weights = list(arms), [float(w) for w in weights]
    if not arms or len(arms) != len(weights):
        raise ValueError("need one weight per arm and at least one arm")
    if any(not math.isfinite(w) or w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("weights must be finite, non-negative and sum to > 0")
    total = sum(weights)

    def combined(original: str, candidate: str) -> float:
        acc = 0.0
        for arm, w in zip(arms, weights):
            s = float(arm(original, candidate))
            if not 0.0 <= s <= 1.0:
                raise ValueError(f"arm score {s!r} outside [0, 1]")
            acc += w * s
        return min(1.0, acc / total)

    return combined

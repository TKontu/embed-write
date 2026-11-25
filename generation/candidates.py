"""Request-sized candidate helpers for GE-03.

Unwired by design until GE-04 produces candidates from the local LLM endpoint.
No model or embedder is called here. Callers supply the similarity cutoff.
These helpers operate on one small request (typically single-digit candidate
counts), never a corpus: sampling uses O(n) space; deduplication uses O(k^2)
cosine comparisons, O(k^2 d) time and O(k + d) auxiliary space for dimension d.
There is no enforced request-size cap; large-request performance is untested.
"""

from dataclasses import replace
import math
from typing import Sequence

from generation.run_record import SamplingParams
from service.vectors import LevelVector, cosine


def vary_sampling(base: SamplingParams, n: int) -> list[SamplingParams]:
    """Return n reproducible settings with seeds base.seed through base.seed+n-1.

    Temperatures lie in the fixed range [0.2, 1.0]. Clamp the base temperature
    into that range, then distribute n settings around a cyclic interval of
    width 0.8, starting at the clamped value. For n=1 use the clamped value.
    Preserve top_p and max_tokens; the caller owns endpoint-specific limits.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError('n must be an integer >= 1')
    if not isinstance(base, SamplingParams):
        raise ValueError('base must be SamplingParams')
    if isinstance(base.seed, bool) or not isinstance(base.seed, int):
        raise ValueError('seed must be an integer')
    if (isinstance(base.temperature, bool)
            or not isinstance(base.temperature, (int, float))
            or not math.isfinite(base.temperature)):
        raise ValueError('temperature must be finite')
    start = min(1.0, max(0.2, base.temperature))
    return [replace(base, seed=base.seed + i,
                    temperature=start if i == 0 else
                    0.2 + ((start - 0.2 + 0.8 * i / n) % 0.8))
            for i in range(n)]


def remove_near_duplicates(candidates: Sequence[str], vectors: Sequence[LevelVector],
                           cutoff: float) -> list[str]:
    """Keep the first text in each greedy cluster, preserving input order.

    Drop exact text repeats and any text whose vector has cosine >= cutoff
    with an already kept vector. Validate all vectors through cosine before
    filtering, including duplicates: mixed levels, mismatched dimensions and
    zero vectors raise. Empty inputs return an empty list. Text equality is
    exact, without whitespace or case normalization.
    """
    if (isinstance(cutoff, bool) or not isinstance(cutoff, (int, float))
            or not 0 < cutoff <= 1):
        raise ValueError('cutoff must satisfy 0 < cutoff <= 1')
    if len(candidates) != len(vectors):
        raise ValueError('candidates and vectors must have equal lengths')
    if not all(isinstance(text, str) for text in candidates):
        raise ValueError('candidates must be strings')
    for vector in vectors:
        cosine(vectors[0], vector)
    kept = []
    seen = set()
    for index, text in enumerate(candidates):
        if text in seen:
            continue
        if any(cosine(vectors[index], vectors[other]) >= cutoff for other in kept):
            continue
        kept.append(index)
        seen.add(text)
    return [candidates[index] for index in kept]

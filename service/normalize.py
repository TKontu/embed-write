"""Default L2 normalization (NM-01).

Unwired by design until EM-01's embedder calls these functions. Level typing
belongs to EM-03; this module does not compare vectors across levels.
"""

import math
from collections.abc import Iterable, Iterator, Sequence


class NormalizationError(ValueError):
    """A vector is empty, zero, or contains a non-finite component."""


def l2_normalize(vec: Sequence[float]) -> list[float]:
    """Return a unit vector without mutating input or overflowing its norm.

    Scale before squaring, and divide in scaled coordinates so even a true
    norm larger than the largest float need not be represented.
    """
    if not vec:
        raise NormalizationError("Cannot normalize an empty vector")
    scale = 0.0
    for value in vec:
        if not math.isfinite(value):
            raise NormalizationError("Vector components must be finite")
        scale = max(scale, abs(value))
    if scale == 0.0:
        raise NormalizationError("Cannot normalize a zero vector")
    norm = math.sqrt(math.fsum((value / scale) ** 2 for value in vec))
    return [(value / scale) / norm for value in vec]


def l2_normalize_batch(vectors: Iterable[Sequence[float]]) -> Iterator[list[float]]:
    """Yield normalized vectors lazily, retaining no batch or prior outputs.

    Memory is O(d) for the current output of dimension d, with O(1) batch
    overhead. Invalid vectors raise when reached during iteration.
    """
    for vector in vectors:
        yield l2_normalize(vector)

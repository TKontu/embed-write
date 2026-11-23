"""Optional prefix truncation for embedding backends (EM-04).

unwired by design until EM-02 declares truncatable_dims for a candidate model.
Residuals: no real-model quality or private-corpus path exercised. Callers own
bounded text sequences; embedding retains the full output, and truncation adds
O(n * requested_dims) output memory plus O(d) per-vector temporary memory.
"""

from collections.abc import Sequence

from service.embedder import Embedder, EmbedderError, embed
from service.normalize import l2_normalize
from service.vectors import Level, LevelVector


class TruncationError(EmbedderError):
    """A backend does not support the requested truncation dimensions."""


def supported_dims(embedder: Embedder) -> tuple[int, ...]:
    """Return sorted declared dimensions, or only the native dimension.

    Malformed backend declarations raise EmbedderError; they are never silently
    treated as permission to truncate. No extra protocol member is required.
    """
    native = embedder.dims
    if type(native) is not int or native < 1:
        raise EmbedderError('backend dims must be a positive integer')
    try:
        dimensions = tuple(getattr(embedder, 'truncatable_dims', (native,)))
    except TypeError as exc:
        raise EmbedderError('truncatable_dims must be an iterable of integers') from exc
    if any(type(d) is not int or not 1 <= d <= native for d in dimensions):
        raise EmbedderError('truncatable_dims must contain integers within backend dims')
    return tuple(sorted(dimensions))


def truncate(vector: LevelVector, dims: int) -> LevelVector:
    """Normalize a prefix at the same level; full dimension preserves identity.

    A zero prefix propagates NormalizationError from l2_normalize.
    """
    if type(dims) is not int:
        raise TypeError('dims must be an integer')
    if not 1 <= dims <= len(vector.values):
        raise ValueError('dims must be between 1 and the vector dimension')
    if dims == len(vector.values):
        return vector
    return LevelVector(vector.level, l2_normalize(vector.values[:dims]))


def embed_truncated(embedder: Embedder, texts: Sequence[str], level: Level,
                    dims: int, *, batch_size: int = 64) -> list[LevelVector]:
    """Validate backend support, embed in bounded batches, then truncate."""
    if type(dims) is not int or dims not in supported_dims(embedder):
        raise TruncationError('backend does not support requested dimensions')
    vectors = embed(embedder, texts, level, batch_size=batch_size)
    if dims == embedder.dims:
        return vectors
    return [truncate(vector, dims) for vector in vectors]

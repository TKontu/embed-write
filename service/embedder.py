"""Model-agnostic local embedding contract and a development-only hash stub.

Unwired by design until EM-02/SV-02 provide a model and the service handler
calls embed. Backends must return vectors in input order: vectors carry no
text identity, so the wrapper cannot detect a backend's semantic reordering.
The wrapper holds at most batch_size input references per call, plus the full
returned vector list. The caller also owns the input sequence.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from typing import Protocol

from service.normalize import l2_normalize
from service.vectors import Level, LevelVector


class EmbedderError(RuntimeError):
    """A backend violated the embedding contract."""


class Embedder(Protocol):
    """Local backend; return exactly one vector per text, in input order."""

    model_id: str
    model_version: str
    dims: int

    def embed(self, texts: Sequence[str], level: Level) -> list[LevelVector]:
        ...


def embed(embedder: Embedder, texts: Sequence[str], level: Level, *,
          batch_size: int = 64) -> list[LevelVector]:
    """Validate and embed bounded batches, retaining their input order.

    Input errors raise TypeError/ValueError; malformed backend results raise
    EmbedderError. Backend execution exceptions propagate to the caller.
    """
    if not isinstance(level, Level):
        raise TypeError('level must be a Level')
    if isinstance(texts, (str, bytes, bytearray)) or not isinstance(texts, Sequence):
        raise TypeError('texts must be a sequence of strings, not a bare string')
    if any(not isinstance(text, str) for text in texts):
        raise TypeError('every text must be a string')
    if type(batch_size) is not int:
        raise TypeError('batch_size must be an integer')
    if batch_size <= 0:
        raise ValueError('batch_size must be positive')
    dims = embedder.dims
    if type(dims) is not int or dims <= 0:
        raise EmbedderError('backend dims must be a positive integer')

    result = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        vectors = embedder.embed(batch, level)
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise EmbedderError('backend must return a list with one vector per text')
        for vector in vectors:
            if not isinstance(vector, LevelVector):
                raise EmbedderError('backend returned a non-LevelVector item')
            if vector.level is not level:
                raise EmbedderError('backend returned the wrong level')
            if len(vector.values) != dims:
                raise EmbedderError('backend returned the wrong dimensions')
        result.extend(vectors)
    return result


@dataclass(frozen=True)
class HashEmbedder:
    """Deterministic stdlib stub for tests/development, NOT a semantic model.

    Version 1 hashes length-prefixed UTF-8 model_id, level and text, then
    expands the SHA-256 seed with counter hashes to support arbitrary dims.
    It maps 32-bit words into [-1, 1] and L2-normalizes each vector.
    """

    model_id: str = 'hash-stub'
    dims: int = 32
    model_version: str = '1'

    def __post_init__(self):
        if type(self.dims) is not int:
            raise TypeError('dims must be an integer')
        if self.dims <= 0:
            raise ValueError('dims must be positive')
        if not isinstance(self.model_id, str) or not isinstance(self.model_version, str):
            raise TypeError('model_id and model_version must be strings')

    def embed(self, texts: Sequence[str], level: Level) -> list[LevelVector]:
        """Implement the backend contract; use module-level embed for validation."""
        result = []
        for text in texts:
            seed = hashlib.sha256()
            for field in (self.model_id, level.value, text):
                encoded = field.encode('utf-8')
                seed.update(len(encoded).to_bytes(8, 'big'))
                seed.update(encoded)
            values = []
            for counter in range((self.dims + 7) // 8):
                block = hashlib.sha256(seed.digest() + counter.to_bytes(8, 'big')).digest()
                for offset in range(0, 32, 4):
                    word = int.from_bytes(block[offset:offset + 4], 'big')
                    values.append(2 * word / (2**32 - 1) - 1)
            result.append(LevelVector(level, l2_normalize(values[:self.dims])))
        return result

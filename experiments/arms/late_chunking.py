"""Late-chunking arm for G-03.

Production caller: G-03 runner arm, unwired by design until G-03 wiring.
One section costs O(tokens*d) backend memory plus O(sentences*d) output.
The caller must bound sections by the model context length (untested here).
No real model or quality measurement is supplied.
"""
from collections.abc import Sequence
import math
from typing import Protocol

from service.normalize import NormalizationError, l2_normalize
from service.vectors import Level, LevelVector

LATE_CHUNKING = 'late_chunking'


class LateChunkingError(ValueError):
    """Invalid spans or token embeddings."""


class TokenEmbedder(Protocol):
    """Embed one section once; ordered, disjoint, nonempty character spans.

    Offsets are Python string indices, half-open [start, end). Backends must
    omit special tokens without text offsets. Execution exceptions propagate.
    """

    def embed_tokens(self, text: str) -> tuple[Sequence[Sequence[float]],
                                              Sequence[tuple[int, int]]]:
        ...


def _validate_spans(spans, length):
    previous_end = 0
    for span in spans:
        if (not isinstance(span, (tuple, list)) or len(span) != 2
                or any(type(v) is not int for v in span)):
            raise LateChunkingError('spans must be integer pairs')
        start, end = span
        if not 0 <= start < end <= length or start < previous_end:
            raise LateChunkingError('spans must be in range, sorted and non-overlapping')
        previous_end = end


def late_chunk(section_text: str, sentence_spans: Sequence[tuple[int, int]],
               token_embedder: TokenEmbedder, level: Level) -> list[LevelVector]:
    """Mean-pool all tokens overlapping each sentence, then L2-normalize.

    Sorted disjoint intervals allow a moving pointer, O(tokens + sentences)
    interval visits; a token crossing a boundary contributes to both sentences.
    A zero pooled vector is an error. Empty sentence input returns no vectors.
    """
    if not isinstance(level, Level):
        raise TypeError('level must be a Level')
    _validate_spans(sentence_spans, len(section_text))
    if not sentence_spans:
        return []
    vectors, spans = token_embedder.embed_tokens(section_text)
    _validate_spans(spans, len(section_text))
    if len(vectors) != len(spans):
        raise LateChunkingError('token vector and span counts must match')
    dims = len(vectors[0]) if vectors else 0
    for vector in vectors:
        if not dims or len(vector) != dims:
            raise LateChunkingError('token vector dimensions must match and be nonempty')
        if not all(math.isfinite(v) for v in vector):
            raise LateChunkingError('token vectors must be finite')
    result = []
    first = 0
    for start, end in sentence_spans:
        while first < len(spans) and spans[first][1] <= start:
            first += 1
        stop = first
        while stop < len(spans) and spans[stop][0] < end:
            stop += 1
        count = stop - first
        if not count:
            raise LateChunkingError('sentence has no overlapping token')
        try:
            mean = [math.fsum(vectors[j][i] / count for j in range(first, stop))
                    for i in range(dims)]
            result.append(LevelVector(level, l2_normalize(mean)))
        except (NormalizationError, OverflowError) as exc:
            raise LateChunkingError('pooled vector cannot be normalized') from exc
        # Keep a straddling token for the next sentence.
        first = stop - 1 if spans[stop - 1][1] > end else stop
    return result

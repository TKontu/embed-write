"""Deterministic contextual-prefix arm for G-03.

Production caller: G-03 runner arm, unwired by design until G-03 wiring.
Prefixed texts occupy O(batch_size * text) memory, plus O(chunks*d) output.
Context paths are caller-supplied; no real model or LLM summary is supplied.
"""
from collections.abc import Callable, Sequence

from service.chunk import Chunk
from service.embedder import Embedder, embed
from service.vectors import Level, LevelVector

CONTEXTUAL_PREFIX = 'contextual_prefix'


class ContextualPrefixError(ValueError):
    """Invalid context path or prefix options."""


def build_prefixed_text(text: str, context: Sequence[str], *,
                        separator=' > ', max_prefix_chars=256) -> str:
    """Prepend a stripped path, capped in Python characters, preserving text."""
    if max_prefix_chars <= 0:
        raise ContextualPrefixError('max_prefix_chars must be positive')
    if separator == '':
        raise ContextualPrefixError('separator must not be empty')
    parts = []
    for part in context:
        if not isinstance(part, str):
            raise ContextualPrefixError('context parts must be strings')
        if '\n' in part or '\r' in part:
            raise ContextualPrefixError('context parts must not contain newlines')
        stripped = part.strip()
        if stripped:
            parts.append(stripped)
    prefix = separator.join(parts)[:max_prefix_chars]
    return f'{prefix}\n\n{text}' if prefix else text


def contextual_embed(chunks: Sequence[Chunk],
                     context_for: Callable[[Chunk], Sequence[str]],
                     embedder: Embedder, level: Level, *, batch_size=64,
                     **prefix_options) -> list[LevelVector]:
    """Embed one lazily constructed batch at a time via the validated wrapper.

    The requested level tags every result; backend and callback exceptions
    propagate. Input chunks and the complete output remain caller-owned.
    """
    if type(batch_size) is not int:
        raise TypeError('batch_size must be an integer')
    if batch_size <= 0:
        raise ValueError('batch_size must be positive')
    if not isinstance(level, Level):
        raise TypeError('level must be a Level')
    result = []
    for start in range(0, len(chunks), batch_size):
        texts = [build_prefixed_text(chunks[i].text, context_for(chunks[i]),
                                     **prefix_options)
                 for i in range(start, min(start + batch_size, len(chunks)))]
        result.extend(embed(embedder, texts, level, batch_size=batch_size))
    return result

"""Slow-layer cache; unwired by design until LY-02 (slow path) calls it.

Stores opaque values (normally Signals) by content and context hashes supplied by
LY-02. In-memory and not thread-safe. O(max_entries) entries and index records;
individual value/hash byte sizes are unbounded. No corpus or model is loaded.
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int
    size: int


def _validate_hash(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f'{name} must be a string')
    if not value:
        raise ValueError(f'{name} must not be empty')


class SlowLayerCache:
    """Bounded LRU; reads and writes promote entries to most recently used."""

    def __init__(self, max_entries: int):
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError('max_entries must be an int >= 1')
        self._max = max_entries
        self._entries: OrderedDict[tuple[str, str], Any] = OrderedDict()
        self._contexts: dict[str, set[str]] = {}
        self._hits = self._misses = self._evictions = 0

    def get(self, content_hash: str, context_hash: str) -> Any:
        """Return the original value or None; stored None still counts as a hit."""
        _validate_hash(content_hash, 'content_hash')
        _validate_hash(context_hash, 'context_hash')
        key = (content_hash, context_hash)
        if key in self._entries:
            self._entries.move_to_end(key)
            self._hits += 1
            return self._entries[key]
        self._misses += 1
        return None

    def put(self, content_hash: str, context_hash: str, value: Any) -> None:
        _validate_hash(content_hash, 'content_hash')
        _validate_hash(context_hash, 'context_hash')
        key = (content_hash, context_hash)
        self._entries[key] = value
        self._entries.move_to_end(key)
        self._contexts.setdefault(content_hash, set()).add(context_hash)
        if len(self._entries) > self._max:
            (content, context), _ = self._entries.popitem(last=False)
            contexts = self._contexts[content]
            contexts.remove(context)
            if not contexts:
                del self._contexts[content]
            self._evictions += 1

    def invalidate_content(self, content_hash: str) -> None:
        """Drop all contexts for content in O(entries for that content) time."""
        _validate_hash(content_hash, 'content_hash')
        for context in self._contexts.pop(content_hash, ()):
            del self._entries[(content_hash, context)]

    def clear(self) -> None:
        """Remove entries and index records, preserving lifetime counters."""
        self._entries.clear()
        self._contexts.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> CacheStats:
        """Return a snapshot; only capacity removal counts as eviction."""
        return CacheStats(self._hits, self._misses, self._evictions, len(self))

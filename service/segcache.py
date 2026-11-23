"""Segmentation cache (CK-03): bounded LRU of sentence segmentations keyed by block content hash.

``SegmentationCache.get(text)`` returns the segmenter's sentences for a block as an immutable
tuple, calling the segmenter only on a miss. The key is ``(segmenter token, key_version,
node_hash(text))``; identical text in different blocks shares one entry, and bumping
``key_version`` moves a changed segmenter into a fresh keyspace.

Production caller: CK-02 sentence segmentation feeding CK-01 chunking. Unwired by design until
CK-02 lands. Not thread-safe; in-memory only (persistence is CA-*).

Memory is bounded by ``max_entries`` entries; the byte size of each entry is not bounded (it is
proportional to the block text). The 100 000-word document bound is untested here.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Sequence

from service.contract import node_hash


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int
    size: int


class SegmentationCache:
    def __init__(self, segmenter: Callable[[str], Sequence[str]], max_entries: int,
                 key_version: str = "v1"):
        if not callable(segmenter):
            raise TypeError("segmenter must be callable")
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be an int >= 1")
        if not isinstance(key_version, str):
            raise TypeError("key_version must be a str")
        self._segmenter = segmenter
        self._token = (id(segmenter), key_version)
        self._max = max_entries
        self._entries: OrderedDict = OrderedDict()
        self._hits = self._misses = self._evictions = 0

    def _key(self, block_hash: str) -> tuple:
        return (self._token, block_hash)

    def get(self, block_text: str) -> tuple:
        if not isinstance(block_text, str):
            raise TypeError("block_text must be a str")
        key = self._key(node_hash(block_text))
        if key in self._entries:
            self._entries.move_to_end(key)
            self._hits += 1
            return self._entries[key]
        self._misses += 1
        result = self._segmenter(block_text)
        if isinstance(result, (str, bytes)) or not isinstance(result, Sequence):
            raise TypeError("segmenter must return a sequence of str")
        sentences = tuple(result)
        if not all(isinstance(s, str) for s in sentences):
            raise TypeError("segmenter must return a sequence of str")
        self._entries[key] = sentences
        if len(self._entries) > self._max:
            self._entries.popitem(last=False)
            self._evictions += 1
        return sentences

    def invalidate(self, block_hash: str) -> None:
        self._entries.pop(self._key(block_hash), None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> CacheStats:
        return CacheStats(self._hits, self._misses, self._evictions, len(self._entries))

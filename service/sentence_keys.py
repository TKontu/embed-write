"""Stable sentence keys inside a block (NI-05).

``sentence_keys`` derives one key per sentence from the block ID and the
caller-supplied sentence content hashes. The first occurrence of a hash in a
block gets ``"<block_id>:<hash>"``; later repeats get ``"<block_id>:<hash>#<n>"``
with n = 1, 2, ... so duplicate sentences receive distinct, deterministic keys.

The hash function is not chosen here: HS-01 owns content hashing and callers
pass the hashes in.

Unwired by design until HI-03 (sentence layer) and the edit log call it.

Residual: keys of repeated sentences depend on their order within the block;
inserting a duplicate before an existing one shifts the existing suffixes.
"""

from __future__ import annotations

from collections.abc import Sequence

_RESERVED = (":", "#")


def sentence_keys(block_id: str, sentence_hashes: Sequence[str]) -> tuple[str, ...]:
    """Return one stable key per sentence hash, in input order.

    Raises ValueError for an empty block_id, an empty hash, or a hash
    containing ':' or '#'.
    """
    if not block_id:
        raise ValueError("block_id must be non-empty")
    seen: dict[str, int] = {}
    keys: list[str] = []
    for digest in sentence_hashes:
        if not digest:
            raise ValueError("sentence hash must be non-empty")
        if any(ch in digest for ch in _RESERVED):
            raise ValueError(f"sentence hash must not contain ':' or '#': {digest!r}")
        count = seen.get(digest, 0)
        seen[digest] = count + 1
        base = f"{block_id}:{digest}"
        keys.append(base if count == 0 else f"{base}#{count}")
    return tuple(keys)

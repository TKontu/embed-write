"""Client/service contract (SV-03): the client sends dirty node sets, never whole documents.

A request carries only nodes whose content hash differs from the hash the client last sent (or is
unknown). The service validates every item: each carries a ``hash`` matching its text, ids are
unique, and no node text exceeds ``max_node_chars`` -- the bound that keeps whole documents out.

``node_hash`` is a stub (sha256 of UTF-8 text) until todo-03 supplies document-model hashes.
Production callers: ``service/client.py`` (AnalysisClient) and ``service/server.py`` (/v1/batch).
"""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

DEFAULT_MAX_NODE_CHARS = 20000


class ContractError(ValueError):
    """A request violates the dirty-node contract."""


def node_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dirty_nodes(current: Mapping[str, str], known_hashes: Mapping[str, str]) -> list:
    """Nodes of ``current`` whose hash is new or changed, in ``current`` order."""
    out = []
    for node_id, text in current.items():
        h = node_hash(text)
        if known_hashes.get(node_id) != h:
            out.append({"id": node_id, "hash": h, "text": text})
    return out


def build_request(current: Mapping[str, str], known_hashes: Mapping[str, str]) -> dict:
    return {"items": dirty_nodes(current, known_hashes)}


def validate_items(items: Sequence[dict], max_node_chars: int = DEFAULT_MAX_NODE_CHARS) -> None:
    seen = set()
    for i, item in enumerate(items):
        node_id, text, h = item.get("id"), item.get("text"), item.get("hash")
        if not isinstance(node_id, str) or not isinstance(text, str):
            raise ContractError(f"items[{i}] must have string 'id' and 'text'")
        if not isinstance(h, str):
            raise ContractError(f"items[{i}] ({node_id!r}) lacks a string 'hash'")
        if h != node_hash(text):
            raise ContractError(f"items[{i}] ({node_id!r}) hash does not match its text")
        if node_id in seen:
            raise ContractError(f"items[{i}] repeats id {node_id!r}")
        seen.add(node_id)
        if len(text) > max_node_chars:
            raise ContractError(
                f"items[{i}] ({node_id!r}) text of {len(text)} chars exceeds {max_node_chars}"
            )

"""Pure in-memory reconciliation for LY-04; O(live keys) storage.

Unwired by design until LY-01/LY-02 provide fast and slow production callers.
Offers are ordered by arrival, not computed_at. The caller owns async staleness
rejection (LY-05); a different content hash starts a fresh state for that key.
"""

from analysis.signals import Signal


def _validate_hash(content_hash: str) -> None:
    if not isinstance(content_hash, str):
        raise TypeError("content_hash must be a string")
    if not content_hash:
        raise ValueError("content_hash must not be empty")


class LayerReconciler:
    """Retain one original Signal and content hash per (node, level, kind)."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], tuple[Signal, str]] = {}

    def offer(self, signal: Signal, content_hash: str) -> str:
        """Offer a result, returning the transition taken in O(1) expected time.

        Changed content is treated as empty before selecting the transition.
        Confirmed results win over provisional ones only for identical content.
        """
        if not isinstance(signal, Signal):
            raise TypeError("signal must be a Signal")
        _validate_hash(content_hash)
        key = (signal.node_id, signal.level, signal.kind)
        previous = self._entries.get(key)
        old_layer = (
            previous[0].layer
            if previous is not None and previous[1] == content_hash
            else "empty"
        )
        if signal.layer == "provisional":
            if old_layer == "confirmed":
                return "ignored_provisional"
            transition = (
                "replace_provisional" if old_layer == "provisional"
                else "set_provisional"
            )
        else:
            transition = "replace_confirmed" if old_layer == "confirmed" else "confirm"
        self._entries[key] = (signal, content_hash)
        return transition

    def current(self, node_id: str, level: str, kind: str) -> Signal | None:
        """Return the stored signal unchanged, or None for an empty key."""
        entry = self._entries.get((node_id, level, kind))
        return entry[0] if entry is not None else None

    def state(self, node_id: str, level: str, kind: str) -> str:
        """Return empty, provisional or confirmed for this key."""
        signal = self.current(node_id, level, kind)
        return signal.layer if signal is not None else "empty"

    def invalidate(self, node_id: str, content_hash: str) -> None:
        """Drop this node's entries for other content hashes.

        Scans O(live keys); the deletion list uses at most O(live keys) memory.
        Other nodes and entries matching the supplied hash remain unchanged.
        """
        _validate_hash(content_hash)
        stale = [key for key, (_, stored_hash) in self._entries.items()
                 if key[0] == node_id and stored_hash != content_hash]
        for key in stale:
            del self._entries[key]

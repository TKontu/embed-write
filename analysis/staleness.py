"""Slow-review staleness guard; unwired by design until LY-02 calls it.

In-memory, synchronous and not thread-safe. The caller supplies content hashes
and reports edits in order. Storage is O(tracked nodes + open tickets), with
unbounded individual string sizes. Completion releases each ticket; current
hashes remain for the lifetime of the guard. No corpus or model is loaded.
"""


def _validate_string(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f'{name} must be a string')
    if not value:
        raise ValueError(f'{name} must not be empty')


class StalenessGuard:
    """Compare a review's starting hash with the node's latest known hash."""

    def __init__(self) -> None:
        self._current: dict[str, str] = {}
        self._tickets: dict[object, tuple[str, str]] = {}
        self._discard_count = 0

    @property
    def discard_count(self) -> int:
        """Number of completed reviews rejected for changed content."""
        return self._discard_count

    def start(self, node_id: str, content_hash: str) -> object:
        """Return an opaque, single-use ticket belonging to this guard.

        Initialize an unknown node's current hash. For known nodes, start never
        overwrites edit observations: callers must report changes via note_edit.
        """
        _validate_string(node_id, 'node_id')
        _validate_string(content_hash, 'content_hash')
        self._current.setdefault(node_id, content_hash)
        ticket = object()
        self._tickets[ticket] = (node_id, content_hash)
        return ticket

    def note_edit(self, node_id: str, content_hash: str) -> None:
        """Record current content, even before the node's first review."""
        _validate_string(node_id, 'node_id')
        _validate_string(content_hash, 'content_hash')
        self._current[node_id] = content_hash

    def accept(self, ticket: object) -> bool:
        """Consume a ticket, accepting only a matching current content hash.

        Unknown, foreign or consumed tickets raise ValueError; invalid types
        raise TypeError. These errors do not increment the discard counter.
        """
        if type(ticket) is not object:
            raise TypeError('ticket must be an opaque object returned by start')
        try:
            node_id, content_hash = self._tickets.pop(ticket)
        except KeyError:
            raise ValueError('unknown or already consumed ticket') from None
        accepted = self._current[node_id] == content_hash
        if not accepted:
            self._discard_count += 1
        return accepted

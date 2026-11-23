"""IR-01 dirty-set protocol: ``{changedNodeIds, newHashes}`` in, affected signals out.

Production caller: the editor/app-shell recompute loop; unwired by design until
NI-01/NI-05 supply node ids and content hashes.

A changed id whose new hash equals its old hash is a no-op. The remaining ids
go through ``service.dirty.dirty_set`` (self plus ancestors); a signal is
affected iff its node_id is dirty at the level whose ``Level.value`` equals
``signal.level``. Nothing is recomputed here.

Scale: O(signals + changed * depth) time; signals are consumed once. Memory is
O(signals) for the result tuples (no streaming result) plus O(nodes) for the
hash map copy.

Residuals: the 100 000-word document bound is untested; IR-03 late-chunking
sibling invalidation is out of scope; synthetic tests only.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from analysis.signals import Signal
from service.dirty import Hierarchy, dirty_set
from service.vectors import Level


@dataclass(frozen=True)
class DirtyRequest:
    changed_node_ids: frozenset[str]
    new_hashes: Mapping[str, str]

    def __post_init__(self):
        ids = frozenset(self.changed_node_ids)
        hashes = dict(self.new_hashes)
        for node_id in ids:
            if not isinstance(node_id, str) or not node_id:
                raise ValueError('changed node ids must be non-empty str')
        missing = ids - hashes.keys()
        if missing:
            raise ValueError(f'changed ids without a new hash: {sorted(missing)}')
        extra = hashes.keys() - ids
        if extra:
            raise ValueError(f'new hashes for unchanged ids: {sorted(extra)}')
        for node_id, value in hashes.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f'hash for {node_id!r} must be a non-empty str')
        object.__setattr__(self, 'changed_node_ids', ids)
        object.__setattr__(self, 'new_hashes', MappingProxyType(hashes))


@dataclass(frozen=True)
class InvalidationResult:
    dirty: dict[Level, frozenset[str]]
    affected: tuple[Signal, ...]
    kept: tuple[Signal, ...]
    hashes: Mapping[str, str]


def affected_signals(hierarchy: Hierarchy,
                     old_hashes: Mapping[str, str],
                     request: DirtyRequest,
                     signals: Iterable[Signal]) -> InvalidationResult:
    """Split ``signals`` into affected and kept for one dirty-set request."""
    effective = {node_id: new for node_id, new in request.new_hashes.items()
                 if old_hashes.get(node_id) != new}
    # Sorted for a deterministic walk; KeyError on unknown id from dirty_set.
    # No-op ids are validated too so unknown ids never pass silently.
    for node_id in request.changed_node_ids:
        hierarchy.node(node_id)
    dirty = dirty_set(hierarchy, sorted(effective))
    by_value = {level.value: ids for level, ids in dirty.items()}
    affected: list[Signal] = []
    kept: list[Signal] = []
    for signal in signals:
        if signal.node_id in by_value.get(signal.level, frozenset()):
            affected.append(signal)
        else:
            kept.append(signal)
    hashes = dict(old_hashes)
    hashes.update(effective)
    return InvalidationResult(dirty=dirty, affected=tuple(affected),
                              kept=tuple(kept), hashes=MappingProxyType(hashes))

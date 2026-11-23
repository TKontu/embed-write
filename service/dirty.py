"""IR-02 ancestor invalidation: changed nodes dirty themselves and their ancestors.

Unwired by design until IR-01 consumes the dirty set and NI-01/NI-05 supply
node ids.

Scale: ``Hierarchy.from_nodes`` is O(nodes) time and memory and consumes its
input once; ``dirty_set`` is O(changed * depth) with depth <= 3.

Residuals: the 100 000-word document bound is untested; IR-03 late-chunking
sibling invalidation is out of scope (siblings are never dirtied here).
"""

from collections.abc import Iterable
from dataclasses import dataclass

from service.vectors import Level

_PARENT_LEVEL = {
    Level.SENTENCE: Level.BLOCK,
    Level.BLOCK: Level.SECTION,
    Level.SECTION: None,
}


@dataclass(frozen=True)
class NodeRef:
    node_id: str
    level: Level
    parent_id: str | None

    def __post_init__(self):
        if not isinstance(self.node_id, str) or not self.node_id:
            raise ValueError('node_id must be a non-empty str')
        if not isinstance(self.level, Level):
            raise TypeError('level must be a Level')
        if self.parent_id is not None and (
                not isinstance(self.parent_id, str) or not self.parent_id):
            raise ValueError('parent_id must be None or a non-empty str')


class Hierarchy:
    """Validated section -> block -> sentence parent map."""

    __slots__ = ('_nodes',)

    def __init__(self, nodes: dict[str, NodeRef]):
        self._nodes = nodes

    @classmethod
    def from_nodes(cls, nodes: Iterable[NodeRef]) -> 'Hierarchy':
        by_id: dict[str, NodeRef] = {}
        for node in nodes:
            if not isinstance(node, NodeRef):
                raise TypeError('nodes must be NodeRef instances')
            if node.node_id in by_id:
                raise ValueError(f'duplicate node_id {node.node_id!r}')
            by_id[node.node_id] = node
        for node in by_id.values():
            expected = _PARENT_LEVEL[node.level]
            if expected is None:
                if node.parent_id is not None:
                    raise ValueError(f'section {node.node_id!r} must have no parent')
                continue
            if node.parent_id is None:
                raise ValueError(f'{node.level.value} {node.node_id!r} needs a parent')
            parent = by_id.get(node.parent_id)
            if parent is None:
                raise ValueError(f'unknown parent id {node.parent_id!r}')
            if parent.level is not expected:
                raise ValueError(
                    f'{node.level.value} {node.node_id!r} parent must be a '
                    f'{expected.value}, got {parent.level.value}')
        # Strictly increasing level along every parent edge rules out cycles.
        return cls(by_id)

    def __len__(self) -> int:
        return len(self._nodes)

    def node(self, node_id: str) -> NodeRef:
        return self._nodes[node_id]


def dirty_set(hierarchy: Hierarchy,
              changed_ids: Iterable[str]) -> dict[Level, frozenset[str]]:
    """Return every changed id plus all its ancestors, keyed by level."""
    dirty: dict[Level, set[str]] = {level: set() for level in Level}
    for node_id in changed_ids:
        node = hierarchy.node(node_id)  # KeyError on unknown id
        while True:
            bucket = dirty[node.level]
            if node.node_id in bucket:
                break
            bucket.add(node.node_id)
            if node.parent_id is None:
                break
            node = hierarchy.node(node.parent_id)
    return {level: frozenset(ids) for level, ids in dirty.items()}

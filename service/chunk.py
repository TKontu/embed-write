"""CK-01 structural chunks from document-model blocks, without parsing structure.

Production caller: unwired by design until IR-01/SV-02. Wires CK-06 and
CK-03; callers configure SegmentationCache with CK-02 segment_sentences and
its SEGMENTER_ID. Input node/section ids belong to the document model; it
must keep block ids distinct from the generated ``<block_id>#s<i>`` ids.

chunk_blocks holds only the current block and its cached segmentation, with
O(1) additional chunks. Cache entries are bounded by max_entries, not bytes.
hierarchy_for explicitly materializes O(chunks) NodeRefs; sections are supplied
by the caller. The 100 000-word operating bound remains untested.
"""
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from service.block_policy import embed_text_for
from service.dirty import NodeRef
from service.segcache import SegmentationCache
from service.vectors import Level


@dataclass(frozen=True)
class Block:
    node_id: str
    section_id: str
    block_type: str
    text: str
    caption: str | None = None
    header_row: Sequence[str] | None = None


@dataclass(frozen=True)
class Chunk:
    node_id: str
    level: Level
    parent_id: str
    text: str


def chunk_blocks(blocks: Iterable[Block], segcache: SegmentationCache) -> Iterator[Chunk]:
    """Yield each embeddable block, then its zero-indexed sentences if prose."""
    for block in blocks:
        text = embed_text_for(block.block_type, text=block.text,
                              caption=block.caption, header_row=block.header_row)
        if not text:
            continue
        yield Chunk(block.node_id, Level.BLOCK, block.section_id, text)
        if block.block_type in ('paragraph', 'caption'):
            for index, sentence in enumerate(segcache.get(text)):
                yield Chunk(f'{block.node_id}#s{index}', Level.SENTENCE,
                            block.node_id, sentence)


def hierarchy_for(chunks: Iterable[Chunk]) -> list[NodeRef]:
    """Project chunk identities; add document-model SECTION NodeRefs to validate.

    Hierarchy.from_nodes performs identity and parent validation, including
    duplicate ids. This helper never invents sections or reparses chunk text.
    """
    return [NodeRef(chunk.node_id, chunk.level, chunk.parent_id) for chunk in chunks]

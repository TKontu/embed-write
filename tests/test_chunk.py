"""Synthetic offline checks for structural chunking (R52/A1)."""
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock

from service.chunk import Block, Chunk, chunk_blocks, hierarchy_for
from service.dirty import Hierarchy, NodeRef
from service.segcache import SegmentationCache
from service.segment import SEGMENTER_ID, segment_sentences
from service.vectors import Level


class ChunkTests(unittest.TestCase):
    def setUp(self):
        self.segmenter = Mock(return_value=('First.', 'Second.'))
        self.cache = SegmentationCache(self.segmenter, max_entries=2)

    def test_paragraph_sentences_have_deterministic_ids_and_parents(self):
        block = Block('p', 'supplied-section', 'paragraph', 'First. Second.')
        expected = [Chunk('p', Level.BLOCK, 'supplied-section', block.text),
                    Chunk('p#s0', Level.SENTENCE, 'p', 'First.'),
                    Chunk('p#s1', Level.SENTENCE, 'p', 'Second.')]
        self.assertEqual(list(chunk_blocks([block], self.cache)), expected)
        self.assertEqual(list(chunk_blocks([block], self.cache)), expected)

    def test_caption_is_segmented_from_its_text(self):
        block = Block('c', 's', 'caption', 'First. Second.', caption='ignored')
        chunks = list(chunk_blocks([block], self.cache))
        self.assertEqual([c.text for c in chunks], [block.text, 'First.', 'Second.'])
        self.assertEqual(chunks[1].parent_id, 'c')
        self.segmenter.assert_called_once_with(block.text)

    def test_table_uses_caption_and_headers_only(self):
        block = Block('t', 's', 'table', 'private body', 'Table caption.', ('A', 'B'))
        self.assertEqual(list(chunk_blocks([block], self.cache)),
                         [Chunk('t', Level.BLOCK, 's', 'Table caption.\nA | B')])
        self.segmenter.assert_not_called()

    def test_figure_uses_caption_only(self):
        block = Block('f', 's', 'figure', 'image body', 'Figure caption.')
        self.assertEqual(list(chunk_blocks([block], self.cache)),
                         [Chunk('f', Level.BLOCK, 's', 'Figure caption.')])
        self.segmenter.assert_not_called()

    def test_code_is_skipped(self):
        self.assertEqual(list(chunk_blocks([Block('c', 's', 'code', 'print(1)')],
                                           self.cache)), [])
        self.segmenter.assert_not_called()

    def test_empty_policy_text_has_no_chunks_or_cache_call(self):
        for kind in ('paragraph', 'caption', 'table', 'figure'):
            with self.subTest(kind=kind):
                self.assertEqual(list(chunk_blocks([Block('b', 's', kind, '')],
                                                   self.cache)), [])
        self.segmenter.assert_not_called()

    def test_unknown_block_type_raises(self):
        with self.assertRaisesRegex(ValueError, 'Unknown block type'):
            list(chunk_blocks([Block('x', 's', 'unknown', '')], self.cache))

    def test_input_consumed_only_when_next_block_is_needed(self):
        consumed = []
        def source():
            for node in ('a', 'b'):
                consumed.append(node)
                yield Block(node, 's', 'paragraph', 'First. Second.')
        chunks = chunk_blocks(iter(source()), self.cache)
        self.assertEqual(consumed, [])
        self.assertEqual(next(chunks).node_id, 'a')
        self.segmenter.assert_not_called()
        self.assertEqual(next(chunks).node_id, 'a#s0')
        self.assertEqual(next(chunks).node_id, 'a#s1')
        self.assertEqual(consumed, ['a'])
        self.assertEqual(next(chunks).node_id, 'b')
        self.assertEqual(consumed, ['a', 'b'])

    def test_cache_shares_distinct_text_across_blocks(self):
        blocks = [Block(str(i), 's', 'paragraph', text)
                  for i, text in enumerate(('First.', 'Other.', 'First.'))]
        list(chunk_blocks(iter(blocks), self.cache))
        self.assertEqual(self.segmenter.call_count, 2)
        self.assertEqual(self.cache.stats().hits, 1)

    def test_hierarchy_accepts_nodes_with_supplied_sections(self):
        blocks = [Block('a', 's2', 'paragraph', '# Not a section.'),
                  Block('b', 's1', 'figure', '', 'Caption')]
        refs = hierarchy_for(chunk_blocks(iter(blocks), self.cache))
        self.assertIsInstance(refs, list)
        hierarchy = Hierarchy.from_nodes([NodeRef('s1', Level.SECTION, None),
                                          NodeRef('s2', Level.SECTION, None), *refs])
        self.assertEqual(hierarchy.node('a').parent_id, 's2')
        self.assertEqual(hierarchy.node('a#s1').parent_id, 'a')
        self.assertEqual(hierarchy.node('b').parent_id, 's1')

    def test_real_segmenter_through_cache(self):
        cache = SegmentationCache(segment_sentences, 2, key_version=SEGMENTER_ID)
        chunks = list(chunk_blocks([Block('p', 's', 'paragraph',
                                          'Dr. Smith measured 2.5 cm. It worked.')], cache))
        self.assertEqual([c.text for c in chunks[1:]],
                         ['Dr. Smith measured 2.5 cm.', 'It worked.'])

    def test_empty_input(self):
        self.assertEqual(list(chunk_blocks(iter(()), self.cache)), [])
        self.assertEqual(hierarchy_for(iter(())), [])

    def test_block_is_frozen(self):
        block = Block('p', 's', 'paragraph', 'Text')
        with self.assertRaises(FrozenInstanceError):
            block.text = 'Changed'

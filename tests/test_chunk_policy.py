"""D-006 paths through chunk_blocks using synthetic LLM-built blocks (R55/A3)."""
import unittest
from unittest.mock import Mock

from service.chunk import Block, Chunk, chunk_blocks
from service.segcache import SegmentationCache
from service.segment import SEGMENTER_ID, segment_sentences
from service.vectors import Level


class ChunkPolicyTests(unittest.TestCase):
    def setUp(self):
        self.segmenter = Mock(wraps=segment_sentences)
        self.cache = SegmentationCache(self.segmenter, 2, key_version=SEGMENTER_ID)

    def assert_policy(self, block, expected, *, prose=False):
        self.assertEqual(list(chunk_blocks(iter([block]), self.cache)), expected)
        if prose:
            self.segmenter.assert_called_once_with(block.text)
        else:
            self.segmenter.assert_not_called()

    def test_code_is_skipped_even_with_caption_and_header(self):
        self.assert_policy(Block('code', 'section', 'code', 'print(1)',
                                 'Ignored caption.', ('Ignored header',)), [])

    def test_figure_embeds_only_caption_without_sentences(self):
        self.assert_policy(
            Block('fig', 'section', 'figure', 'Ignored image body.',
                  'First caption. Second caption.', ('Ignored header',)),
            [Chunk('fig', Level.BLOCK, 'section', 'First caption. Second caption.')])

    def test_figure_without_caption_is_skipped(self):
        self.assert_policy(Block('fig', 'section', 'figure', 'Ignored image body.',
                                 header_row=('Ignored header',)), [])

    def test_table_with_caption_only(self):
        self.assert_policy(
            Block('table', 'section', 'table', 'Ignored cells.', 'Table caption.'),
            [Chunk('table', Level.BLOCK, 'section', 'Table caption.')])

    def test_table_with_header_only(self):
        self.assert_policy(
            Block('table', 'section', 'table', 'Ignored cells.',
                  header_row=('Name', 'Value')),
            [Chunk('table', Level.BLOCK, 'section', 'Name | Value')])

    def test_table_with_caption_and_header(self):
        self.assert_policy(
            Block('table', 'section', 'table', 'Ignored cells.',
                  'Table caption.', ('Name', 'Value')),
            [Chunk('table', Level.BLOCK, 'section', 'Table caption.\nName | Value')])

    def test_table_without_caption_or_header_is_skipped(self):
        self.assert_policy(Block('table', 'section', 'table', 'Ignored cells.'), [])

    def test_caption_text_emits_block_then_sentences(self):
        self.assert_policy(
            Block('caption', 'section', 'caption', 'First caption. Second caption.',
                  'Ignored metadata.', ('Ignored header',)),
            [Chunk('caption', Level.BLOCK, 'section', 'First caption. Second caption.'),
             Chunk('caption#s0', Level.SENTENCE, 'caption', 'First caption.'),
             Chunk('caption#s1', Level.SENTENCE, 'caption', 'Second caption.')], prose=True)

    def test_paragraph_text_emits_block_then_sentences(self):
        self.assert_policy(
            Block('para', 'section', 'paragraph', 'First sentence. Second sentence.',
                  'Ignored metadata.', ('Ignored header',)),
            [Chunk('para', Level.BLOCK, 'section', 'First sentence. Second sentence.'),
             Chunk('para#s0', Level.SENTENCE, 'para', 'First sentence.'),
             Chunk('para#s1', Level.SENTENCE, 'para', 'Second sentence.')], prose=True)

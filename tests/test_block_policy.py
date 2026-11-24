"""Synthetic, offline checks of the D-006 embedding policy."""

import unittest

from service.block_policy import embed_text_for


class BlockPolicyTests(unittest.TestCase):
    def test_code_is_skipped(self):
        self.assertIsNone(embed_text_for('code', text='print(1)', caption='code'))

    def test_figure_uses_only_caption(self):
        self.assertEqual(embed_text_for('figure', text='body', caption=' Figure 1 '),
                         ' Figure 1 ')

    def test_figure_without_caption_is_skipped(self):
        for caption in (None, ''):
            with self.subTest(caption=caption):
                self.assertIsNone(embed_text_for('figure', text='body', caption=caption))

    def test_table_joins_caption_and_header_without_body(self):
        header = ['Name', 'Value']
        self.assertEqual(embed_text_for('table', text='body', caption='Table 1',
                                        header_row=header), 'Table 1\nName | Value')
        self.assertEqual(header, ['Name', 'Value'])

    def test_table_with_only_caption(self):
        for header in (None, []):
            with self.subTest(header=header):
                self.assertEqual(embed_text_for('table', caption='Table 1',
                                                header_row=header), 'Table 1')

    def test_table_with_only_header(self):
        for caption in (None, ''):
            with self.subTest(caption=caption):
                self.assertEqual(embed_text_for('table', caption=caption,
                                                header_row=('A', 'B')), 'A | B')

    def test_table_without_caption_or_header_is_skipped(self):
        for caption in (None, ''):
            for header in (None, []):
                with self.subTest(caption=caption, header=header):
                    self.assertIsNone(embed_text_for('table', text='body',
                                                      caption=caption, header_row=header))

    def test_caption_uses_text_unchanged(self):
        self.assertEqual(embed_text_for('caption', text=' Caption\n', caption='ignored'),
                         ' Caption\n')
        self.assertEqual(embed_text_for('caption'), '')

    def test_paragraph_uses_text_unchanged(self):
        self.assertEqual(embed_text_for('paragraph', text=' Paragraph\n', caption='ignored'),
                         ' Paragraph\n')
        self.assertEqual(embed_text_for('paragraph'), '')

    def test_unknown_type_is_rejected(self):
        for block_type in ('unknown', '', 'Paragraph'):
            with self.subTest(block_type=block_type):
                with self.assertRaises(ValueError):
                    embed_text_for(block_type)


if __name__ == '__main__':
    unittest.main()

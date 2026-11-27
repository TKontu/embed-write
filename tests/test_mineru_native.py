"""D-016 MinerU native adapter tests. content_list fixtures are synthetic, LLM-built; no network."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from experiments import ingest, mineru_native as mn

BLOCKS = [
    {"type": "header", "text": "Running Head"},
    {"type": "text", "text": "Intro Title", "text_level": 1},
    {"type": "text", "text": "Sub part", "text_level": 2},
    {"type": "text", "text": "A plain paragraph."},
    {"type": "list", "list_items": ["first item", "second item"]},
    {"type": "equation", "text": "$$\nE = mc^2\n$$", "text_format": "latex"},
    {"type": "table", "table_caption": ["Table 1: Results"],
     "table_body": "<table><tr><th>Name</th><th>Value</th></tr>"
                   "<tr><td>alpha</td><td>1 &amp; 2</td></tr></table>",
     "table_footnote": ["Source: synthetic."]},
    {"type": "image", "image_caption": ["Figure 1: A diagram."], "img_path": "images/x.jpg"},
    {"type": "chart", "chart_caption": []},
    {"type": "page_number", "text": "3"},
    {"type": "footer", "text": "Footer text"},
    {"type": "page_number", "text": "4"},
    {"type": "aside_text", "text": "Side note."},
    {"type": "mystery", "text": "Kept text."},
    "not a dict",
]


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.md, self.dropped = mn.content_list_to_markdown(BLOCKS, ingest._md_escape, ingest._table)

    def test_every_block_type(self):
        md = self.md
        self.assertTrue(md.startswith("# Intro Title\n\n## Sub part\n\nA plain paragraph.\n\n"))
        self.assertIn("first item\nsecond item", md)
        self.assertIn("$$\nE = mc^2\n$$", md)
        self.assertIn("Table 1: Results\n\n| Name | Value |\n| --- | --- |\n| alpha | 1 & 2 |", md)
        self.assertIn("Source: synthetic.", md)
        self.assertIn("Figure: Figure 1: A diagram.", md)
        self.assertIn("\\[chart\\]", md)
        self.assertIn("Side note.", md)
        self.assertIn("Kept text.", md)
        self.assertEqual(ingest.count_headings(md), 2)

    def test_chrome_dropped_and_counted(self):
        for s in ("Running Head", "Footer text", "\n3\n", "\n4\n"):
            self.assertNotIn(s, self.md)
        self.assertEqual(self.dropped, {"footer": 1, "header": 1, "page_number": 2})

    def test_heading_level_capped_and_body_escaped(self):
        md, _ = mn.content_list_to_markdown(
            [{"type": "text", "text": "Deep", "text_level": 9},
             {"type": "text", "text": "# not a heading", "text_level": 0}], ingest._md_escape)
        self.assertEqual(md, "###### Deep\n\n\\# not a heading\n")

    def test_envelope_with_string_content_list(self):
        raw = {"results": {"doc": {"content_list": json.dumps(BLOCKS[:2])}}}
        self.assertEqual(len(mn.content_list_of(raw)), 2)
        with self.assertRaises(ValueError):
            mn.content_list_of({"results": {}})

    def test_request_fields(self):
        body, ctype = mn._multipart(b"%PDF-data", "r.pdf")
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        for name, value in mn.FIELDS:
            self.assertIn(f'name="{name}"\r\n\r\n{value}\r\n'.encode(), body)
        self.assertIn(b'name="files"; filename="r.pdf"', body)
        self.assertEqual(dict(mn.FIELDS), {"backend": "pipeline", "lang_list": "en",
                                           "return_content_list": "true", "return_images": "true"})

    def test_settings(self):
        with mock.patch.dict(os.environ, {"PARSER_BASE_URL": "", "PARSER_TIMEOUT_S": ""}):
            self.assertEqual(mn.settings(), ("", 300.0))
        with mock.patch.dict(os.environ, {"PARSER_BASE_URL": " http://h:1 ", "PARSER_TIMEOUT_S": "7"}):
            self.assertEqual(mn.settings(), ("http://h:1", 7.0))


if __name__ == "__main__":
    unittest.main()

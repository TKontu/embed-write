"""CO-14 section inference (D-015). All fixtures are LLM-built synthetic text, never corpus data."""
import unittest

from experiments.section_inference import infer_sections


def starts(secs):
    return [(s["start_line"], s["level"], s["method"]) for s in secs]


class InferSectionsTest(unittest.TestCase):
    def test_numbered_headings(self):
        md = ("1. Introduction\n\nThe pump was tested.\n\n2.3 Method details\n\n"
              "We measured flow.\n\nIV. Results\n\nFlow rose.\n\nA) Annex\n\nTables follow.\n")
        secs = infer_sections(md)
        self.assertEqual(starts(secs), [(0, 1, "numbering"), (4, 2, "numbering"),
                                        (8, 1, "numbering"), (12, 1, "numbering")])
        for s in secs:
            self.assertIs(s["inferred"], True)
            self.assertEqual(s["title_line"], s["start_line"])

    def test_bold_and_short_lines(self):
        md = ("**Background of the study**\n\nSome text here.\n\nScope and limits\n\n"
              "More text follows here.\n")
        self.assertEqual(starts(infer_sections(md)), [(0, 1, "formatting"), (4, 1, "formatting")])

    def test_numbered_list_is_not_headings(self):
        md = ("Steps taken.\n\n1. Open the valve\n2. Close the valve\n3. Record\n\n"
              "Done with steps.\n")
        self.assertEqual(infer_sections(md), [])

    def test_code_fence_and_indented_code_never_qualify(self):
        md = ("Intro text.\n\n```\n\n1. Fake heading\n\n**Bold fake**\n\nbody\n```\n\n"
              "    Indented fake\n\nReal prose paragraph.\n")
        self.assertEqual(infer_sections(md), [])

    def test_sentence_line_not_heading(self):
        md = "A short sentence.\n\nAnother paragraph of prose.\n"
        self.assertEqual(infer_sections(md), [])

    def test_empty(self):
        self.assertEqual(infer_sections(""), [])

    def test_deterministic(self):
        md = "1. Intro\n\nText.\n\n**Next part**\n\nMore text.\n"
        self.assertEqual(infer_sections(md), infer_sections(md))
        self.assertEqual(len(infer_sections(md)), 2)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "methods" / "llm-not-final-judge.md"


class MethodLlmNotFinalJudgeTest(unittest.TestCase):
    def test_doc_exists_and_names_biases(self):
        self.assertTrue(DOC.is_file(), f"missing {DOC}")
        text = DOC.read_text(encoding="utf-8").lower()
        for term in ("position", "verbosity", "self-preference", "expert"):
            self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()

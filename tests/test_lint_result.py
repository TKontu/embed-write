"""Behavior checks for the gate result-report lint (X-03)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lint_result.py"
TEMPLATE = ROOT / "experiments" / "results" / "TEMPLATE.md"

COMPLETE = """# G-99 — Synthetic gate

## Hypothesis
The synthetic classifier separates A from B.

## Threshold
AUC >= 0.8, fixed before the run.

## Method
Held-out synthetic pairs; LLM-built labels; scored by script.

## Numbers
AUC 0.84 (95% CI 0.79-0.88), n=200 pairs; population: synthetic pairs;
metric: AUC; reference: LLM-built labels; built by: LLM.

## Verdict
passed

## Fallback taken
none
"""


class LintResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def lint(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True, text=True,
        )

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_template_passes_in_template_mode(self):
        result = self.lint("--template", TEMPLATE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_template_fails_as_real_report(self):
        result = self.lint(TEMPLATE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("placeholder", result.stdout)

    def test_complete_fixture_passes(self):
        result = self.lint(self.write("G-99.md", COMPLETE))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_verdict_fails(self):
        text = COMPLETE.replace("## Verdict\npassed\n\n", "")
        result = self.lint(self.write("G-99.md", text))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Verdict", result.stdout)
        self.assertIn("missing", result.stdout)

    def test_empty_section_fails(self):
        text = COMPLETE.replace("## Verdict\npassed\n", "## Verdict\n\n")
        result = self.lint(self.write("G-99.md", text))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Verdict", result.stdout)
        self.assertIn("empty", result.stdout)

    def test_numbers_without_sample_size_fails(self):
        text = COMPLETE.replace("n=200 pairs", "200 pairs")
        result = self.lint(self.write("G-99.md", text))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("n=", result.stdout)

    def test_template_mode_still_requires_sections(self):
        text = COMPLETE.replace("## Fallback taken\nnone\n", "")
        result = self.lint("--template", self.write("T.md", text))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fallback taken", result.stdout)

    def test_reports_each_failing_file(self):
        good = self.write("good.md", COMPLETE)
        bad = self.write("bad.md", "# nothing\n")
        result = self.lint(good, bad)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bad.md", result.stdout)
        self.assertNotIn("good.md", result.stdout)

    def test_missing_file_fails(self):
        result = self.lint(self.dir / "absent.md")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

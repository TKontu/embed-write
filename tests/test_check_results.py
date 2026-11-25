"""Behavior checks for the result-report CI wiring (X-03)."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_results.py"

REGISTRY = """[[gate]]
id = "G-01"
title = "Synthetic"
status = "{status}"
result_doc = "experiments/results/G-01.md"
flags_unlocked = []
"""


def complete_fixture():
    from tests.test_lint_result import COMPLETE
    return COMPLETE


class CheckResultsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        results = self.root / "experiments" / "results"
        results.mkdir(parents=True)
        shutil.copy(ROOT / "experiments" / "results" / "TEMPLATE.md", results / "TEMPLATE.md")
        self.results = results

    def run_check(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, cwd=ROOT)

    def registry(self, status):
        path = self.root / "registry.toml"
        path.write_text(REGISTRY.format(status=status), encoding="utf-8")
        return path

    def test_shipped_repo_passes(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TEMPLATE.md", result.stdout)

    def test_passed_gate_with_bad_doc_fails(self):
        (self.results / "G-01.md").write_text("# G-01\n\n## Hypothesis\nx\n", encoding="utf-8")
        result = self.run_check("--registry", self.registry("passed"), "--root", self.root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("G-01.md", result.stdout)

    def test_failed_gate_with_good_doc_passes(self):
        (self.results / "G-01.md").write_text(complete_fixture(), encoding="utf-8")
        result = self.run_check("--registry", self.registry("failed"), "--root", self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("G-01.md", result.stdout)

    def test_stray_result_doc_is_linted_even_if_gate_pending(self):
        (self.results / "G-01.md").write_text("# G-01\n", encoding="utf-8")
        result = self.run_check("--registry", self.registry("pending"), "--root", self.root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_bad_template_fails(self):
        (self.results / "TEMPLATE.md").write_text("# T\n", encoding="utf-8")
        result = self.run_check("--registry", self.registry("pending"), "--root", self.root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("TEMPLATE.md", result.stdout)


if __name__ == "__main__":
    unittest.main()

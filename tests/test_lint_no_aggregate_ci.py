import unittest
from pathlib import Path


class LintNoAggregateCITest(unittest.TestCase):
    def test_nightly_runs_no_aggregate_score_lint(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/nightly.yml').read_text(encoding='utf-8')
        self.assertIn('python3 scripts/lint_no_aggregate.py', workflow)

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/lint_levels.py'


class LevelLintTests(unittest.TestCase):
    def lint(self, source):
        self.assertTrue(SCRIPT.exists(), 'level lint is missing')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.py'
            path.write_text(source)
            return subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                  capture_output=True, text=True)

    def test_literal_mismatch(self):
        for name in ('cosine', 'dot'):
            result = self.lint('\n' + name + '(LevelVector(Level.SENTENCE, (1,)), '
                               'LevelVector(level=Level.BLOCK, values=(1,)))\n')
            self.assertEqual(result.returncode, 1)
            self.assertIn('fixture.py:2:', result.stdout)

    def test_same_level_clean(self):
        result = self.lint('dot(LevelVector(Level.SECTION, (1,)), '
                           'LevelVector(Level.SECTION, (2,)))')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_raw_imports_flagged(self):
        for source in ('from scipy.spatial.distance import cosine as c',
                       'import scipy.spatial.distance as distance',
                       'from sklearn.metrics.pairwise import cosine_similarity',
                       'from numpy import dot', 'from numpy import *'):
            with self.subTest(source=source):
                self.assertEqual(self.lint(source).returncode, 1)

    def test_safe_import_clean(self):
        self.assertEqual(self.lint('from service.vectors import cosine, dot').returncode, 0)

    def test_repository_clean(self):
        self.assertTrue(SCRIPT.exists(), 'level lint is missing')
        result = subprocess.run([sys.executable, str(SCRIPT), 'service', 'analysis'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

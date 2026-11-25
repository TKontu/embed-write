import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'lint_no_aggregate.py'


_spec = importlib.util.spec_from_file_location('lint_no_aggregate', SCRIPT)
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)


def run(*paths):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, paths)],
                          capture_output=True, text=True, cwd=ROOT)


class LintNoAggregateTest(unittest.TestCase):
    def check(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.py'
            path.write_text(textwrap.dedent(source), encoding='utf-8')
            result = run(path)
            lines = [line.split(':')[1] for line in result.stdout.splitlines()]
            return result.returncode, lines, result.stdout

    def test_flagged_names(self):
        cases = {
            'def aggregate_score(x):\n    return x\n': '1',
            'x = 1\noverall_score = 2\n': '2',
            'x = 1\ny = 2\nself.combinedScore = 3\n': '3',
            'd = {}\nd = {"composite_score": 1}\n': '2',
            'scoreSum = 1\n': '1',
            'score_mean = 1\n': '1',
            'weighted_sum = 1\n': '1',
            'total_score = 1\n': '1',
            'def f(score_avg=0):\n    pass\n': '1',
        }
        for source, line in cases.items():
            with self.subTest(source=source):
                code, lines, _ = self.check(source)
                self.assertEqual(code, 1)
                self.assertEqual(lines, [line])

    def test_combining_calls(self):
        cases = [
            'a = 1\nr = sum([support_score, length_result])\n',
            'import statistics\na = 1\nr = statistics.mean([s.support_score, n.number_result])\n',
            'import statistics\na = 1\nr = statistics.fmean((a_score, b_score))\n',
            'import numpy as np\na = 1\nr = np.average([a_score, b_result])\n',
            'from statistics import mean\na = 1\nr = mean([a_score, b_score])\n',
        ]
        for source in cases:
            with self.subTest(source=source):
                code, lines, _ = self.check(source)
                self.assertEqual(code, 1)
                expected = str(source.splitlines().index(
                    next(l for l in source.splitlines() if l.startswith('r ='))) + 1)
                self.assertEqual(lines, [expected])

    def test_single_axis_not_flagged(self):
        code, lines, out = self.check('''
            support_score = 0.8
            total = sum([support_score])
            words = sum(len(w) for w in support_score_parts)
            x = sum([a_score, a_score])
            n = sum([count, other])
        ''')
        self.assertEqual((code, out), (0, ''))

    def test_real_modules_pass(self):
        result = run(*(ROOT / 'service' / name for name in
                       ('support_check.py', 'length_delta.py', 'number_check.py')))
        self.assertEqual((result.returncode, result.stdout), (0, ''))

    def test_default_targets_pass(self):
        result = run()
        self.assertEqual((result.returncode, result.stdout), (0, ''))

    def test_panel_implementations_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel = Path(tmp) / 'panel.py'
            panel.write_text(textwrap.dedent('''
                A = AxisEntry(name="a", implementation="service/a.py")
                N = AxisEntry(name="n", implementation=None)
                R = AxisEntry(name="r", implementation="service/a.py")
                B = AxisEntry(name="b", implementation="service/b.py")
            '''), encoding='utf-8')
            self.assertEqual(lint.panel_implementations(panel),
                             ('service/a.py', 'service/b.py'))
            self.assertEqual(lint.panel_implementations(Path(tmp) / 'missing.py'), ())

    def test_default_targets_follow_panel(self):
        targets = lint.default_targets(ROOT / 'service' / 'verify_panel.py')
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(targets[:4], lint.DEFAULT_TARGETS)
        real = lint.panel_implementations(ROOT / 'service' / 'verify_panel.py')
        self.assertTrue(real)
        self.assertTrue(set(real) <= set(targets))


if __name__ == '__main__':
    unittest.main()

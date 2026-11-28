"""G-09.1 legend colour-blind check (experiments/legend_cvd.py)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments import legend_cvd as lc

ROOT = Path(__file__).resolve().parents[1]

# Sharma, Wu & Dalal 2005, Table 1: (Lab1, Lab2, dE00)
SHARMA = [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((50.0, 2.5, 0.0), (61.0, -5.0, 29.0), 22.8977),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


def genre(colors, other='#9a9a9a', moves=None):
    moves = [{'id': k} for k in colors] if moves is None else moves
    return {'moves': moves, 'legend': {'colors': colors, 'other': other}}


class Ciede2000(unittest.TestCase):
    def test_sharma_pairs(self):
        for lab1, lab2, want in SHARMA:
            self.assertAlmostEqual(lc.ciede2000(lab1, lab2), want, delta=1e-4)
            self.assertAlmostEqual(lc.ciede2000(lab2, lab1), want, delta=1e-4)


class Simulation(unittest.TestCase):
    def test_red_green_collapses_under_deutan_only(self):
        rep = lc.check({'gap': '#c0504d', 'method': '#4f9d69'}, 10.0)
        sims = rep['simulations']
        self.assertFalse(sims['deutan']['pass'])
        self.assertEqual(sims['deutan']['below'][0]['a'], 'gap')
        for name in ('normal', 'protan', 'tritan'):
            self.assertTrue(sims[name]['pass'], name)
        self.assertGreater(sims['normal']['min_delta_e'], 50)
        self.assertFalse(rep['pass'])
        self.assertEqual(rep['threshold'], 10.0)


class Cli(unittest.TestCase):
    def run_cli(self, data, *extra):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'g.json'
            p.write_text(data if isinstance(data, str) else json.dumps(data))
            out = Path(d) / 'r.json'
            proc = subprocess.run([sys.executable, '-m', 'experiments.legend_cvd', 'check', str(p),
                                   '--json', str(out), *extra], cwd=ROOT, capture_output=True, text=True)
            report = json.loads(out.read_text()) if out.exists() else None
        return proc, report

    def test_exit_0_and_json(self):
        proc, rep = self.run_cli(genre({'a': '#000000', 'b': '#ffffff'}, other='#808080'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('threshold: CIEDE2000 >= 10.0', proc.stdout)
        self.assertEqual(set(rep['simulations']), {'normal', 'protan', 'deutan', 'tritan'})
        self.assertTrue(rep['pass'])

    def test_exit_1_names_failing_simulation(self):
        proc, rep = self.run_cli(genre({'gap': '#c0504d', 'method': '#4f9d69'}, other='#000000'))
        self.assertEqual(proc.returncode, 1)
        self.assertIn('deutan', proc.stdout)
        self.assertFalse(rep['simulations']['deutan']['pass'])

    def test_threshold_flag(self):
        proc, rep = self.run_cli(genre({'gap': '#c0504d', 'method': '#4f9d69'}, other='#000000'),
                                 '--min-delta-e', '5')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(rep['threshold'], 5.0)

    def test_exit_2_bad_input(self):
        cases = {
            'bad hex': genre({'a': '#12345', 'b': '#ffffff'}),
            'missing legend': {'moves': [{'id': 'a'}]},
            'unknown move': genre({'a': '#000000', 'zz': '#ffffff'}, moves=[{'id': 'a'}]),
            'fewer than 2': {'legend': {'colors': {}, 'other': '#9a9a9a'}},
            'not json': '{',
        }
        for name, data in cases.items():
            proc, rep = self.run_cli(data)
            self.assertEqual(proc.returncode, 2, name)
            self.assertIn('error:', proc.stderr, name)
            self.assertIsNone(rep, name)

    def test_demo_genre_runs(self):
        proc, _ = self.run_cli((ROOT / 'examples/demo/genre.json').read_text())
        self.assertIn(proc.returncode, (0, 1))


if __name__ == '__main__':
    unittest.main()

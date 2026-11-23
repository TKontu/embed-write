import io
import json
import os
import random
import tempfile
import unittest

from experiments.blind_session import build_session, consistency_pairs, record_session_choice
from experiments.consistency import CAUTION, consistency_report, main, to_store_record
from experiments.store import ResultStore


def pairs(agree, disagree):
    out = [(f'p{i}', 'A', 'A') for i in range(agree)]
    out += [(f'q{i}', 'A', 'B') for i in range(disagree)]
    return out


class ReportTests(unittest.TestCase):
    def test_three_of_four(self):
        r = consistency_report(iter(pairs(3, 1)), n_resamples=500)
        self.assertEqual((r['n'], r['agreements'], r['rate']), (4, 3, 0.75))
        lo, hi = r['interval']
        self.assertTrue(0 <= lo <= 0.75 <= hi <= 1)

    def test_tie_counts_as_its_own_winner(self):
        r = consistency_report([('p', 'tie', 'tie'), ('q', 'tie', 'A')], n_resamples=100)
        self.assertEqual(r['rate'], 0.5)

    def test_deterministic_for_seed(self):
        a = consistency_report(pairs(7, 3), n_resamples=1000, seed=5)
        b = consistency_report(pairs(7, 3), n_resamples=1000, seed=5)
        self.assertEqual(a, b)
        self.assertTrue(a['interval'][0] <= 0.7 <= a['interval'][1])

    def test_all_and_none_agree(self):
        self.assertEqual(consistency_report(pairs(5, 0), n_resamples=200)['interval'], (1.0, 1.0))
        r = consistency_report(pairs(0, 5), n_resamples=200)
        self.assertEqual((r['rate'], r['interval']), (0.0, (0.0, 0.0)))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            consistency_report(iter([]))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'choices.jsonl')

    def write_session(self, flip_repeats):
        comps = {name: [(f'{name}-{i}', f'x{i}', name[0], f'y{i}', 'C') for i in range(6)]
                 for name in ('A_vs_C', 'B_vs_C')}
        session = build_session(comps, repeat_fraction=0.5, min_gap=2, rng=random.Random(2))
        flipped = 0
        for item in session:
            p = item.presentation
            prefer_c = item.repeat_of is not None and flipped < flip_repeats
            flipped += prefer_c
            wanted = (p._left_arm == 'C') == prefer_c
            record_session_choice(self.path, session, item.item_id,
                                  'left' if wanted else 'right')
        return sum(i.repeat_of is not None for i in session)

    def test_end_to_end_and_store(self):
        n = self.write_session(flip_repeats=2)
        with open(self.path, encoding='utf-8') as f:
            report = consistency_report(consistency_pairs(f), n_resamples=500)
        self.assertEqual((report['n'], report['agreements']), (n, n - 2))
        record = to_store_record(report, gate='G-02', arm='expert', timestamp='t',
                                 commit='c', modelVersion='m', inventoryVersion='i')
        store = ResultStore(':memory:')
        self.addCleanup(store.close)
        store.add(record)
        self.assertEqual([r['metric'] for r in store.query(metric='self_consistency')],
                         ['self_consistency'])

    def run_cli(self, *extra):
        out = io.StringIO()
        main([self.path, '--n-resamples', '200', *extra], out=out)
        return out.getvalue().splitlines()

    def test_cli_caution_only_below_threshold(self):
        n = self.write_session(flip_repeats=0)
        lines = self.run_cli()
        self.assertEqual(json.loads(lines[0])['rate'], 1.0)
        self.assertEqual(len(lines), 1)
        open(self.path, 'w').close()
        n = self.write_session(flip_repeats=2)
        lines = self.run_cli()
        self.assertEqual(json.loads(lines[0])['n'], n)
        self.assertEqual(lines[1:], [CAUTION])
        self.assertEqual(len(self.run_cli('--low-threshold', '0.1')), 1)


if __name__ == '__main__':
    unittest.main()

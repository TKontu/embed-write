import json
import math
import os
import random
import tempfile
import unittest

from experiments import blind_pair
from experiments.blind_session import (build_session, consistency_pairs, load_session,
                                       record_session_choice, save_session)


def comparisons(sizes):
    out = {}
    for name, n in sizes.items():
        a, b = name.split('_vs_')
        out[name] = [(f'{name}-{i}', f'text {a} {i}', a, f'text {b} {i}', b) for i in range(n)]
    return out


class BuildSessionTests(unittest.TestCase):
    def test_every_pair_once_as_original(self):
        comps = comparisons({'A_vs_C': 7, 'B_vs_C': 4, 'A_vs_B': 2})
        session = build_session(comps, repeat_fraction=0.2, min_gap=3, rng=random.Random(1))
        originals = [i.presentation.pair_id for i in session if i.repeat_of is None]
        expected = [p[0] for pairs in comps.values() for p in pairs]
        self.assertEqual(sorted(originals), sorted(expected))
        self.assertEqual(len({i.item_id for i in session}), len(session))

    def test_no_consecutive_same_comparison_equal_sizes(self):
        comps = comparisons({'A_vs_C': 10, 'B_vs_C': 10, 'A_vs_B': 10})
        for seed in range(30):
            # Strict for originals; repeat placement avoids adjacency best-effort only.
            for fraction in (0, 0.1, 0.25, 0.5):
                session = build_session(comps, repeat_fraction=fraction, min_gap=4,
                                        rng=random.Random(seed))
                for a, b in zip(session, session[1:]):
                    self.assertNotEqual(a.comparison, b.comparison, (seed, fraction))

    def test_repeat_count_and_gap(self):
        comps = comparisons({'A_vs_C': 9, 'B_vs_C': 8})
        total = 17
        for seed in range(20):
            session = build_session(comps, repeat_fraction=0.25, min_gap=5, rng=random.Random(seed))
            repeats = [i for i in session if i.repeat_of is not None]
            self.assertEqual(len(repeats), math.ceil(0.25 * total))
            index = {i.item_id: n for n, i in enumerate(session)}
            for r in repeats:
                original = session[index[r.repeat_of]]
                self.assertIsNone(original.repeat_of)
                self.assertEqual(original.presentation.pair_id, r.presentation.pair_id)
                self.assertGreaterEqual(index[r.item_id] - index[r.repeat_of], 5)
                self.assertNotEqual(original.presentation.key, r.presentation.key)

    def test_repeat_order_is_rerandomised(self):
        comps = comparisons({'A_vs_C': 20, 'B_vs_C': 20})
        session = build_session(comps, repeat_fraction=1, min_gap=1, rng=random.Random(3))
        by_id = {i.item_id: i for i in session}
        flips = [by_id[r.repeat_of].presentation.left != r.presentation.left
                 for r in session if r.repeat_of]
        self.assertTrue(any(flips) and not all(flips))

    def test_infeasible_min_gap_raises(self):
        comps = comparisons({'A_vs_C': 3, 'B_vs_C': 3})
        with self.assertRaises(ValueError):
            build_session(comps, repeat_fraction=0.5, min_gap=6, rng=random.Random(0))
        with self.assertRaises(ValueError):
            build_session(comps, repeat_fraction=1, min_gap=2, rng=random.Random(0))

    def test_rendered_repeat_has_no_metadata(self):
        comps = comparisons({'Alpha_vs_Gamma': 6, 'Beta_vs_Gamma': 6})
        comps = {k: [(p, f'plain text {n}', ax, f'other words {n}', ay)
                     for n, (p, _, ax, _, ay) in enumerate(v)] for k, v in comps.items()}
        session = build_session(comps, repeat_fraction=0.5, min_gap=2, rng=random.Random(5))
        repeats = [i for i in session if i.repeat_of]
        self.assertTrue(repeats)
        for item in repeats:
            html = blind_pair.render_html(item.presentation)
            for marker in (item.repeat_of, item.item_id, 'repeat', 'Repeat', 'item-',
                           'Alpha', 'Beta', 'Gamma', item.presentation.pair_id,
                           item.presentation.key, item.comparison):
                self.assertNotIn(marker, html)

    def test_seeded_determinism(self):
        comps = comparisons({'A_vs_C': 8, 'B_vs_C': 5})
        def shape(seed):
            s = build_session(comps, repeat_fraction=0.3, min_gap=3, rng=random.Random(seed))
            return [(i.item_id, i.comparison, i.repeat_of, i.presentation.pair_id,
                     i.presentation.left) for i in s]
        self.assertEqual(shape(11), shape(11))
        self.assertNotEqual(shape(11), shape(12))


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_save_load_round_trip(self):
        session = build_session(comparisons({'A_vs_C': 4, 'B_vs_C': 4}), repeat_fraction=0.25,
                                min_gap=2, rng=random.Random(2))
        path = os.path.join(self.dir.name, 'session.json')
        save_session(path, session)
        self.assertEqual(load_session(path), session)

    def test_choices_and_consistency_both_orders(self):
        comps = comparisons({'A_vs_C': 20, 'B_vs_C': 20})
        session = build_session(comps, repeat_fraction=1, min_gap=1, rng=random.Random(4))
        by_id = {i.item_id: i for i in session}
        path = os.path.join(self.dir.name, 'choices.jsonl')
        expected, orders = {}, set()
        for item in session:
            p = item.presentation
            # Judge always prefers the non-C arm, whatever side it is on.
            choice = 'left' if p._left_arm != 'C' else 'right'
            record_session_choice(path, session, item.item_id, choice, reason='r')
            if item.repeat_of:
                orig = by_id[item.repeat_of].presentation
                orders.add(orig.left == p.left)
                expected[p.pair_id] = (p._left_arm if choice == 'left' else p._right_arm,) * 2
        self.assertEqual(orders, {True, False})
        with open(path, encoding='utf-8') as f:
            lines = list(f)
        first = json.loads(lines[0])
        self.assertEqual(first['item_id'], session[0].item_id)
        self.assertEqual(first['comparison'], session[0].comparison)
        self.assertIsNone(first['repeat_of'])
        with open(path, encoding='utf-8') as f:
            got = {pid: (a, b) for pid, a, b in consistency_pairs(f)}
        self.assertEqual(got, expected)

    def test_consistency_detects_disagreement_any_record_order(self):
        records = [
            dict(item_id='item-3', pair_id='p', winner='C', repeat_of='item-0'),
            dict(item_id='item-0', pair_id='p', winner='A', repeat_of=None),
            dict(item_id='item-1', pair_id='q', winner='tie', repeat_of=None),
        ]
        self.assertEqual(list(consistency_pairs(records)), [('p', 'A', 'C')])

    def test_record_choice_extra_cannot_override(self):
        pres = blind_pair.make_pair('p', 'x', 'A', 'y', 'B', random.Random(0))
        path = os.path.join(self.dir.name, 'c.jsonl')
        with self.assertRaises(ValueError):
            blind_pair.record_choice(path, pres, 'left', extra={'winner': 'B'})
        self.assertFalse(os.path.exists(path))

    def test_unknown_item_raises(self):
        session = build_session(comparisons({'A_vs_C': 2}), repeat_fraction=0, min_gap=1,
                                rng=random.Random(0))
        with self.assertRaises(KeyError):
            record_session_choice(os.path.join(self.dir.name, 'c'), session, 'nope', 'left')


if __name__ == '__main__':
    unittest.main()

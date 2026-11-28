"""G-02 gate: preference rates from blind choices. LLM-built synthetic fixtures only."""
import json
import random
import unittest

from experiments.gates import g02


def item(item_id, comparison, left, right, repeat_of=None, pair_id=None):
    return dict(item_id=item_id, comparison=comparison, repeat_of=repeat_of,
                pair_id=pair_id or item_id, left='synthetic L', right='synthetic R', key='k',
                left_arm=left, right_arm=right)


def choice(it, side, reason=None):
    winner = 'tie' if side == 'tie' else it['left_arm'] if side == 'left' else it['right_arm']
    return json.dumps(dict(pair_id=it['pair_id'], choice=side, winner=winner, reason=reason,
                           recorded_at='2026-01-01T00:00:00+00:00', item_id=it['item_id'],
                           comparison=it['comparison'], repeat_of=it['repeat_of'])) + '\n'


def fixture():
    s = [item('i1', 'A_vs_C', 'A', 'C'), item('i2', 'A_vs_C', 'C', 'A'),
         item('i3', 'A_vs_C', 'A', 'C'), item('i4', 'A_vs_B', 'B', 'A'),
         item('i5', 'C_vs_original', 'original', 'C'),
         item('i6', 'A_vs_C', 'C', 'A', repeat_of='i1', pair_id='i1')]
    lines = [choice(s[0], 'right'), choice(s[1], 'left'), choice(s[2], 'tie', 'why'),
             choice(s[3], 'left'), choice(s[4], 'left'), choice(s[5], 'left')]
    return s, lines


def run(session, lines, **extra):
    return g02.run(random.Random(3), dict(session=session, choices=lines, n_resamples=200,
                                         **extra))


class G02Test(unittest.TestCase):
    def test_rates_ties_half_first_presentations_only(self):
        s, lines = fixture()
        res = run(s, lines)
        ac = res['comparisons']['A_vs_C']
        self.assertEqual(ac['arm'], 'C')
        self.assertEqual((ac['n'], ac['wins'], ac['losses'], ac['ties']), (3, 2, 0, 1))
        self.assertAlmostEqual(ac['win_rate'], 2.5 / 3, places=6)
        lo, hi = ac['interval']
        self.assertLessEqual(lo, ac['win_rate'])
        self.assertLessEqual(ac['win_rate'], hi)
        self.assertEqual(res['comparisons']['A_vs_B']['arm'], 'B')
        self.assertEqual(res['comparisons']['A_vs_B']['win_rate'], 1.0)
        self.assertEqual(res['comparisons']['C_vs_original']['win_rate'], 0.0)
        self.assertEqual(res['consistency']['n'], 1)
        self.assertEqual(res['consistency']['rate'], 1.0)
        self.assertEqual(res['reasons_nonempty'], 1)

    def test_seeded_reproducible(self):
        s, lines = fixture()
        self.assertEqual(run(s, lines), run(s, lines))

    def test_zero_n_interval_none_with_reason(self):
        s, lines = fixture()
        res = run(s, lines[:3])
        ab = res['comparisons']['A_vs_B']
        self.assertEqual(ab['n'], 0)
        self.assertIsNone(ab['win_rate'])
        self.assertIsNone(ab['interval'])
        self.assertEqual(ab['interval_reason'], 'no_choices')
        self.assertIsNone(res['consistency']['rate'])
        self.assertEqual(res['consistency']['n'], 0)

    def test_completeness_counts(self):
        s, lines = fixture()
        stray = json.loads(lines[0])
        stray['item_id'] = 'zz'
        lines = lines[:4] + [lines[0], json.dumps(stray) + '\n', 'not json\n', '{"torn']
        res = run(s, lines)
        c = res['completeness']
        self.assertEqual(c['unanswered'], 2)
        self.assertEqual(c['unknown_item'], 1)
        self.assertEqual(c['duplicate'], 1)
        self.assertEqual(c['malformed'], 1)
        self.assertEqual(c['torn'], 1)
        self.assertEqual(c['contradicting'], 0)
        self.assertFalse(c['complete'])
        self.assertTrue(run(*fixture())['completeness']['complete'])

    def test_empty_session_not_complete(self):
        c = run([], [])['completeness']
        self.assertEqual(c['session_items'], 0)
        self.assertEqual(c['unanswered'], 0)
        self.assertFalse(c['complete'])

    def test_contradiction_is_error(self):
        s, lines = fixture()
        for key, value in (('comparison', 'A_vs_B'), ('winner', 'B')):
            bad = json.loads(lines[0])
            bad[key] = value
            with self.assertRaises(g02.G02ContradictionError) as cm:
                run(s, [json.dumps(bad) + '\n'] + lines[1:])
            self.assertEqual(cm.exception.completeness['contradicting'], 1)

    def test_choice_winner_mismatch_is_contradiction(self):
        s, lines = fixture()
        for side, winner in (('right', 'A'), ('left', 'tie'), ('bogus', 'tie')):
            bad = json.loads(lines[0])
            bad.update(choice=side, winner=winner)
            with self.assertRaises(g02.G02ContradictionError) as cm:
                run(s, [json.dumps(bad) + '\n'] + lines[1:])
            self.assertEqual(cm.exception.completeness['contradicting'], 1)

    def test_wrong_repeat_of_and_pair_id_are_contradictions(self):
        s, lines = fixture()
        for key, value in (('repeat_of', 'i3'), ('pair_id', 'zzz')):
            bad = json.loads(lines[0])
            bad[key] = value
            with self.assertRaises(g02.G02ContradictionError):
                run(s, [json.dumps(bad) + '\n'] + lines[1:])

    def test_session_contract_validated(self):
        s, lines = fixture()
        wrong_arms = [dict(s[0], left_arm='baseline', right_arm='steered')] + s[1:]
        unknown = [dict(s[0], comparison='B_vs_C')] + s[1:]
        dup = s + [dict(s[0])]
        for sess in (wrong_arms, unknown, dup):
            with self.assertRaises(g02.G02SessionError) as cm:
                run(sess, lines)
            self.assertIn('i1', str(cm.exception))
            self.assertNotIn('synthetic', str(cm.exception))
        self.assertTrue(issubclass(g02.G02SessionError, ValueError))

    def test_verdict_hint(self):
        s, lines = fixture()
        ac = run(s, lines)['comparisons']['A_vs_C']
        self.assertEqual(ac['verdict_hint'], 'meets')
        res = run(s, lines, thresholds={'c_over_a': 0.9})
        self.assertEqual(res['comparisons']['A_vs_C']['verdict_hint'], 'misses')
        self.assertEqual(res['thresholds_source'], 'config')
        self.assertEqual(run(s, lines)['thresholds_source'], 'proposed')
        self.assertEqual(run(s, lines)['thresholds'], {'c_over_a': 0.7})
        res = run(s, lines, thresholds=None)
        self.assertEqual(res['comparisons']['A_vs_C']['verdict_hint'], 'n/a')
        self.assertEqual(run(s, [])['comparisons']['A_vs_C']['verdict_hint'], 'n/a')

    def test_no_status_emitted(self):
        text = json.dumps(run(*fixture())).lower()
        for word in ('passed', 'failed', 'inconclusive', '"status"', 'synthetic l'):
            self.assertNotIn(word, text)


if __name__ == '__main__':
    unittest.main()

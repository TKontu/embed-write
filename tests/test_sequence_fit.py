import json
import unittest

from analysis.detectors import (FOREIGN, MISSING, OUT_OF_ORDER, Detectors,
                                Finding)
from analysis.expected_moves import ExpectedMoves
from analysis.perturb import (delete_move, insert_move, perturb,
                              swap_moves)
from analysis.transitions import LabelledSection, TransitionStats
from experiments.metrics.sequence_fit import (FitScore, match, score,
                                              to_record)


def sec(moves, kind='intro', doc='d'):
    return LabelledSection(doc, kind, tuple(moves))


def f(kind, move, section_type='intro'):
    return Finding(kind, section_type, move, None, ())


class StubDetectors:
    def __init__(self, table):
        self.table = table

    def detect(self, section):
        return tuple(self.table.get((section.document_id,
                                     section.section_type, section.moves),
                                    ()))


class MatchTests(unittest.TestCase):
    def test_delete(self):
        _, p = delete_move(sec('abc'), 1)
        self.assertTrue(match(p, [f(MISSING, 'b')]))
        self.assertFalse(match(p, [f(MISSING, 'a')]))
        self.assertFalse(match(p, [f(FOREIGN, 'b')]))
        self.assertFalse(match(p, [f(MISSING, 'b', 'methods')]))
        self.assertFalse(match(p, []))

    def test_insert(self):
        _, p = insert_move(sec('abc'), 1, 'z')
        self.assertTrue(match(p, [f(MISSING, 'a'), f(FOREIGN, 'z')]))
        self.assertFalse(match(p, [f(FOREIGN, 'y')]))
        self.assertFalse(match(p, [f(MISSING, 'z')]))
        self.assertFalse(match(p, [f(FOREIGN, 'z', 'methods')]))

    def test_swap(self):
        _, p = swap_moves(sec('abc'), 0, 2)
        self.assertTrue(match(p, [f(OUT_OF_ORDER, 'START->c')]))
        self.assertTrue(match(p, [f(OUT_OF_ORDER, 'a->END')]))
        self.assertFalse(match(p, [f(OUT_OF_ORDER, 'START->b')]))
        self.assertFalse(match(p, [f(MISSING, 'a')]))
        self.assertFalse(match(p, [f(OUT_OF_ORDER, 'START->c', 'm')]))


class ScoreTests(unittest.TestCase):
    def test_arithmetic(self):
        s1, p1 = delete_move(sec('abc', doc='d1'), 1)
        s2, p2 = insert_move(sec('abc', doc='d2'), 0, 'z')
        u1, u2, u3 = sec('abc', doc='u1'), sec('abd', 'methods', 'u1'), \
            sec('abc', doc='u2')
        det = StubDetectors({
            ('d1', 'intro', s1.moves): [f(MISSING, 'b'), f(FOREIGN, 'q')],
            ('d2', 'intro', s2.moves): [f(MISSING, 'a')],
            ('u1', 'intro', u1.moves): [f(MISSING, 'x')],
            ('u1', 'methods', u2.moves): [f(MISSING, 'x', 'methods'),
                                          f(FOREIGN, 'y', 'methods')],
        })
        got = score(iter([(s1, p1), (s2, p2)]), iter([u1, u2, u3]), det)
        self.assertEqual(got, FitScore(
            perturbations=2, detected=1, flags_on_perturbed=3, true_flags=1,
            precision=1 / 3, recall=0.5, unperturbed_reports=2,
            false_flags_unperturbed=3, max_false_flags_per_report=3))

    def test_zero_denominators(self):
        got = score([], [], StubDetectors({}))
        self.assertIsNone(got.precision)
        self.assertIsNone(got.recall)
        self.assertEqual(got.max_false_flags_per_report, 0)
        s, p = delete_move(sec('abc'), 0)
        got = score([(s, p)], [], StubDetectors({}))
        self.assertIsNone(got.precision)
        self.assertEqual(got.recall, 0.0)

    def test_to_record_json(self):
        s, p = delete_move(sec('abc'), 0)
        rec = to_record(score([(s, p)], [sec('abc')], StubDetectors({})))
        self.assertEqual(json.loads(json.dumps(rec)), rec)
        self.assertIsNone(rec['precision'])
        self.assertEqual(rec['perturbations'], 1)


class EndToEndTests(unittest.TestCase):
    def test_real_detectors(self):
        corpus = [sec('abcd', doc=f'd{i}') for i in range(10)]
        det = Detectors(TransitionStats.from_sections(corpus),
                        ExpectedMoves.from_sections(corpus))
        held = [sec('abcd', doc=f'h{i}') for i in range(4)]
        pairs = perturb(held, foreign_moves=['z'], seed=7)
        got = score(pairs, iter(held), det)
        self.assertEqual(got.perturbations, 12)
        self.assertEqual(got.detected, 12)
        self.assertEqual(got.recall, 1.0)
        self.assertGreater(got.precision, 0)
        self.assertEqual(got.unperturbed_reports, 4)
        self.assertEqual(got.false_flags_unperturbed, 0)
        json.dumps(to_record(got))


if __name__ == '__main__':
    unittest.main()

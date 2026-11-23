import itertools
import unittest

from analysis.expected_moves import (EXPECTED, OPTIONAL, RARE, ExpectedMoves,
                                     MovePresence)
from analysis.transitions import LabelledSection


def S(doc, kind, *moves):
    return LabelledSection(doc, kind, tuple(moves))


class ExpectedMovesTest(unittest.TestCase):
    def test_repeated_move_counts_once(self):
        em = ExpectedMoves.from_sections([S('d1', 'x', 'a', 'b', 'a', 'a')])
        p = em.presence('x', 'a')
        self.assertEqual(p, MovePresence('a', 1, 1, 1.0, 1, EXPECTED))

    def test_threshold_boundaries_inclusive(self):
        # 10 sections: a in 9 (0.9), b in 1 (0.1), c in 0.
        secs = [S(f'd{i}', 'x', 'a') for i in range(8)]
        secs.append(S('d8', 'x', 'a', 'b'))
        secs.append(S('d9', 'x'))
        em = ExpectedMoves.from_sections(secs, expected_threshold=0.9,
                                         optional_threshold=0.1)
        self.assertEqual(em.presence('x', 'a').role, EXPECTED)
        self.assertEqual(em.presence('x', 'b').role, OPTIONAL)
        self.assertEqual(em.presence('x', 'a').rate, 9 / 10)

    def test_roles(self):
        secs = [S('d1', 'x', 'a', 'b'), S('d2', 'x', 'a'),
                S('d3', 'x', 'a'), S('d4', 'x', 'a', 'c')]
        em = ExpectedMoves.from_sections(secs, expected_threshold=0.75,
                                         optional_threshold=0.5)
        self.assertEqual(em.presence('x', 'a').role, EXPECTED)
        self.assertEqual(em.presence('x', 'b').role, RARE)
        em2 = ExpectedMoves.from_sections(secs, expected_threshold=0.75,
                                          optional_threshold=0.25)
        self.assertEqual(em2.expected('x'), ('a',))
        self.assertEqual(em2.optional('x'), ('b', 'c'))

    def test_documents_with_distinct(self):
        em = ExpectedMoves.from_sections([
            S('d1', 'x', 'a'), S('d1', 'x', 'a'), S('d2', 'x', 'a')])
        p = em.presence('x', 'a')
        self.assertEqual((p.sections_with, p.documents_with), (3, 2))

    def test_types_separate(self):
        em = ExpectedMoves.from_sections([S('d1', 'x', 'a'),
                                          S('d1', 'y', 'b'), S('d2', 'y')])
        self.assertEqual(em.section_types(), ('x', 'y'))
        self.assertIsNone(em.presence('x', 'b'))
        self.assertEqual(em.presence('y', 'b').rate, 0.5)

    def test_empty_sections_count(self):
        em = ExpectedMoves.from_sections([S('d1', 'x'), S('d2', 'x', 'a')])
        self.assertEqual(em.section_count('x'), 2)
        self.assertEqual(em.presence('x', 'a').section_count, 2)
        em2 = ExpectedMoves.from_sections([S('d1', 'z')])
        self.assertEqual((em2.section_count('z'), em2.moves('z')), (1, ()))

    def test_unknown_type(self):
        em = ExpectedMoves.from_sections([S('d1', 'x', 'a')])
        self.assertEqual(em.section_count('q'), 0)
        self.assertEqual(em.moves('q'), ())
        self.assertEqual(em.expected('q'), ())
        self.assertEqual(em.optional('q'), ())
        self.assertIsNone(em.presence('q', 'a'))
        self.assertIsNone(em.presence('x', 'zz'))

    def test_generator_consumed_once(self):
        calls = []

        def gen():
            calls.append(1)
            yield S('d1', 'x', 'a')
            yield S('d2', 'x', 'b')

        g = gen()
        em = ExpectedMoves.from_sections(g)
        self.assertEqual(calls, [1])
        self.assertEqual(list(g), [])
        self.assertEqual(em.section_count('x'), 2)

    def test_invalid_thresholds(self):
        bad = [(0.5, 0), (0.5, 0.6), (1.1, 0.5), (0.5, -0.1), (True, 0.1),
               ('0.9', 0.1)]
        for e, o in bad:
            with self.subTest(e=e, o=o), self.assertRaises(ValueError):
                ExpectedMoves.from_sections([], expected_threshold=e,
                                            optional_threshold=o)
        ExpectedMoves.from_sections([], expected_threshold=1,
                                    optional_threshold=1)

    def test_invalid_items(self):
        for item in (('d1', 'x', ('a',)), None, 'x'):
            with self.subTest(item=item), self.assertRaises(TypeError):
                ExpectedMoves.from_sections([item])

    def test_ordering_deterministic(self):
        secs = [S('d1', 'x', 'c', 'b'), S('d2', 'x', 'b', 'a'),
                S('d3', 'x', 'a', 'd'), S('d4', 'y', 'z')]
        ref = None
        for perm in itertools.permutations(secs):
            em = ExpectedMoves.from_sections(perm, expected_threshold=0.5,
                                             optional_threshold=0.25)
            got = (em.section_types(), em.moves('x'), em.expected('x'),
                   em.optional('x'))
            if ref is None:
                ref = got
            self.assertEqual(got, ref)
        self.assertEqual([p.move for p in ref[1]], ['a', 'b', 'c', 'd'])
        self.assertEqual(ref[2], ('a', 'b'))
        self.assertEqual(ref[3], ('c', 'd'))


if __name__ == '__main__':
    unittest.main()

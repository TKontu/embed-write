import unittest

from analysis.detectors import (FOREIGN, MISSING, OUT_OF_ORDER, Detectors,
                                Finding)
from analysis.expected_moves import ExpectedMoves
from analysis.transitions import LabelledSection, TransitionStats


def sec(moves, kind='intro', doc='d'):
    return LabelledSection(doc, kind, tuple(moves))


def build(sections, **kw):
    sections = list(sections)
    return Detectors(TransitionStats.from_sections(sections),
                     ExpectedMoves.from_sections(sections), **kw)


# 10 sections: 9 x a,b,c and 1 x a,c,b.
CORPUS = [sec('abc', doc=f'd{i}') for i in range(9)] + [sec('acb', doc='d9')]


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.det = build(CORPUS)

    def test_clean_section(self):
        self.assertEqual(self.det.detect(sec('abc')), ())

    def test_model_section_not_flagged_consistent_pattern(self):
        corpus = [sec('abc', doc=f'd{i}') for i in range(5)]
        det = build(corpus)
        for s in corpus:
            self.assertEqual(det.detect(s), ())

    def test_missing_exact_evidence(self):
        self.assertEqual(self.det.missing(sec('ab')), (Finding(
            MISSING, 'intro', 'c', None,
            (('documents_with', 10), ('rate', 1.0), ('section_count', 10),
             ('sections_with', 10))),))

    def test_foreign_unseen_and_rare(self):
        corpus = CORPUS + [sec('abcz', doc='dz')]
        det = build(corpus)  # z rate 1/11 < 0.1 -> RARE
        found = det.foreign(sec('ayzbc'))
        self.assertEqual(found, (
            Finding(FOREIGN, 'intro', 'y', 1,
                    (('documents_with', 0), ('rate', 0.0),
                     ('section_count', 11), ('sections_with', 0))),
            Finding(FOREIGN, 'intro', 'z', 2,
                    (('documents_with', 1), ('rate', 1 / 11),
                     ('section_count', 11), ('sections_with', 1)))))

    def test_foreign_excluded_from_order_pairs(self):
        self.assertEqual(self.det.out_of_order(sec('ayybc')), ())
        self.assertEqual(self.det.foreign(sec('ayybc'))[0].position, 1)

    def test_out_of_order_exact_evidence(self):
        found = self.det.out_of_order(sec('bac'))
        moves = [f.move for f in found]
        self.assertEqual(moves, ['<start>->b', 'b->a'])
        self.assertEqual([f.position for f in found], [0, 1])
        self.assertEqual(found[0].evidence, (
            ('count', 0), ('probability', 0.0), ('section_count', 10),
            ('support', 0)))

    def test_end_pair(self):
        found = self.det.out_of_order(sec('a'))
        self.assertEqual([(f.move, f.position) for f in found],
                         [('a-><end>', 1)])

    def test_threshold_boundary(self):
        # a->c probability 0.1 exactly
        self.assertEqual(
            build(CORPUS, order_threshold=0.1).out_of_order(sec('acb')), ())
        found = build(CORPUS, order_threshold=0.11).out_of_order(sec('acb'))
        self.assertEqual(found[0].move, 'a->c')
        self.assertEqual(found[0].evidence, (
            ('count', 1), ('probability', 0.1), ('section_count', 10),
            ('support', 1)))

    def test_unknown_type(self):
        s = sec('xyz', kind='other')
        for fn in (self.det.missing, self.det.foreign, self.det.out_of_order,
                   self.det.detect):
            self.assertEqual(fn(s), ())

    def test_invalid_threshold(self):
        for bad in (0, -0.1, 1.5, True, '0.1', None):
            with self.assertRaises(ValueError):
                build(CORPUS, order_threshold=bad)
        build(CORPUS, order_threshold=1)

    def test_argument_types(self):
        t = TransitionStats.from_sections(CORPUS)
        e = ExpectedMoves.from_sections(CORPUS)
        with self.assertRaises(TypeError):
            Detectors(e, t)
        with self.assertRaises(TypeError):
            Detectors(t, None)
        for fn in (self.det.missing, self.det.foreign, self.det.out_of_order,
                   self.det.detect):
            with self.assertRaises(TypeError):
                fn(('d', 'intro', ('a',)))

    def test_detect_ordering_deterministic(self):
        s = sec('cyb')
        det = build(CORPUS, order_threshold=0.5)
        found = det.detect(s)
        self.assertEqual([f.kind for f in found],
                         [MISSING, FOREIGN] + [OUT_OF_ORDER] * 3)
        self.assertEqual([f.move for f in found if f.kind == OUT_OF_ORDER],
                         ['<start>->c', 'c->b', 'b-><end>'])
        self.assertEqual(found, det.detect(s))
        positions = [f.position for f in found if f.kind == OUT_OF_ORDER]
        self.assertEqual(positions, sorted(positions))


if __name__ == '__main__':
    unittest.main()

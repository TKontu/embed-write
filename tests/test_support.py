import unittest

from analysis.detectors import (FOREIGN, MISSING, OUT_OF_ORDER, Detectors,
                                Finding)
from analysis.expected_moves import ExpectedMoves
from analysis.support import SupportedFindings, filter_supported, support_of
from analysis.transitions import LabelledSection, TransitionStats


def sec(moves, kind='intro', doc='d'):
    return LabelledSection(doc, kind, tuple(moves))


def build(sections):
    sections = list(sections)
    return Detectors(TransitionStats.from_sections(sections),
                     ExpectedMoves.from_sections(sections))


def missing(docs, move='c'):
    return Finding(MISSING, 'intro', move, None,
                   (('documents_with', docs), ('rate', 1.0),
                    ('section_count', 99), ('sections_with', docs)))


def foreign(count, move='z'):
    return Finding(FOREIGN, 'intro', move, 1,
                   (('documents_with', 99), ('rate', 0.0),
                    ('section_count', count), ('sections_with', 0)))


def order(count, move='b->a'):
    return Finding(OUT_OF_ORDER, 'intro', move, 0,
                   (('count', 0), ('probability', 0.0),
                    ('section_count', count), ('support', 99)))


class SupportOfTests(unittest.TestCase):
    def test_per_kind(self):
        self.assertEqual(support_of(missing(7)), 7)
        self.assertEqual(support_of(foreign(8)), 8)
        self.assertEqual(support_of(order(9)), 9)

    def test_rejects(self):
        with self.assertRaises(TypeError):
            support_of('missing')
        with self.assertRaises(ValueError):
            support_of(Finding('weird', 'intro', 'a', None,
                               (('section_count', 5),)))
        with self.assertRaises(ValueError):
            support_of(Finding(MISSING, 'intro', 'a', None,
                               (('section_count', 5),)))


class FilterTests(unittest.TestCase):
    def test_boundary(self):
        r = filter_supported([missing(5), missing(4)], min_support=5)
        self.assertEqual(r, SupportedFindings((missing(5),), (missing(4),)))
        r = filter_supported([foreign(3), order(2)], min_support=3)
        self.assertEqual(r.kept, (foreign(3),))
        self.assertEqual(r.suppressed, (order(2),))

    def test_order_preserved_and_generator(self):
        items = [order(9, 'x'), missing(1, 'a'), foreign(6, 'b'),
                 missing(2, 'd'), order(5, 'e')]
        r = filter_supported(iter(items))
        self.assertEqual(r.kept, (items[0], items[2], items[4]))
        self.assertEqual(r.suppressed, (items[1], items[3]))

    def test_empty(self):
        self.assertEqual(filter_supported([]), SupportedFindings((), ()))

    def test_invalid_min_support(self):
        for bad in (0, -1, True, 2.0, '5', None):
            with self.assertRaises(ValueError):
                filter_supported([], min_support=bad)

    def test_invalid_items(self):
        with self.assertRaises(TypeError):
            filter_supported([missing(5), 'x'])
        with self.assertRaises(ValueError):
            filter_supported([Finding('weird', 'i', 'a', None, ())])


class EndToEndTests(unittest.TestCase):
    def test_four_documents_suppressed_at_default(self):
        det = build(sec('abc', doc=f'd{i}') for i in range(4))
        found = det.detect(sec('ab'))
        self.assertIn(MISSING, [f.kind for f in found])
        self.assertEqual([support_of(f) for f in found], [4] * len(found))
        r = filter_supported(found)
        self.assertEqual((r.kept, r.suppressed), ((), found))

    def test_supported_corpus_kept(self):
        corpus = [sec('abc', doc=f'd{i}') for i in range(9)]
        corpus.append(sec('acb', doc='d9'))
        found = build(corpus).detect(sec('yba'))
        kinds = {f.kind for f in found}
        self.assertEqual(kinds, {MISSING, FOREIGN, OUT_OF_ORDER})
        r = filter_supported(found)
        self.assertEqual(r.kept, found)
        self.assertEqual(r.suppressed, ())
        r = filter_supported(found, min_support=11)
        self.assertEqual((r.kept, r.suppressed), ((), found))


if __name__ == '__main__':
    unittest.main()

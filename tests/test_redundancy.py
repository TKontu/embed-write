import unittest

from analysis.redundancy import RedundantPair, Unit, redundant_pairs
from service.vectors import CrossLevelError, Level, LevelVector


def vec(*values, level=Level.SENTENCE):
    return LevelVector(level, values)


def unit(node, section, index, *values, level=Level.SENTENCE):
    return Unit(node, section, index, vec(*values, level=level))


class RedundancyTests(unittest.TestCase):
    def test_cross_section_pair_exact_score(self):
        units = [unit('a', 's1', 0, 3, 4), unit('x', 's1', 1, 0, 1),
                 unit('y', 's2', 2, 1, 0), unit('b', 's2', 3, 4, 3)]
        self.assertEqual(redundant_pairs(units, threshold=0.96),
                         (RedundantPair('a', 'b', 's1', 's2', 0.96),))

    def test_same_section_not_reported(self):
        units = [unit('a', 's1', 0, 1, 0), unit('b', 's1', 2, 1, 0)]
        self.assertEqual(redundant_pairs(units), ())

    def test_adjacent_across_boundary_excluded(self):
        units = [unit('a', 's1', 0, 1, 0), unit('b', 's2', 1, 1, 0)]
        self.assertEqual(redundant_pairs(units), ())

    def test_threshold_inclusive(self):
        units = [unit('a', 's1', 0, 3, 4), unit('b', 's2', 2, 4, 3)]
        self.assertEqual(len(redundant_pairs(units, threshold=0.96)), 1)
        self.assertEqual(redundant_pairs(units, threshold=0.9600001), ())

    def test_first_is_earlier_in_document_order(self):
        units = [unit('late', 's2', 5, 1, 0), unit('early', 's1', 0, 1, 0)]
        pair, = redundant_pairs(units)
        self.assertEqual((pair.first, pair.second_section), ('early', 's2'))

    def test_mixed_levels_rejected(self):
        units = [unit('a', 's1', 0, 1, 0), unit('b', 's2', 2, 1, 0, level=Level.BLOCK)]
        with self.assertRaises(CrossLevelError):
            redundant_pairs(units)

    def test_duplicates_rejected(self):
        for units in ([unit('a', 's1', 0, 1), unit('a', 's2', 2, 1)],
                      [unit('a', 's1', 0, 1), unit('b', 's2', 0, 1)]):
            with self.subTest(units=units), self.assertRaises(ValueError):
                redundant_pairs(units)

    def test_invalid_arguments(self):
        units = [unit('a', 's1', 0, 1)]
        for threshold in (-1, 1.5, True, '0.5', float('nan')):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                redundant_pairs(units, threshold=threshold)
        for limit in (0, -1, True, 1.0):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                redundant_pairs(units, limit=limit)
        with self.assertRaises(TypeError):
            redundant_pairs([object()])

    def test_unit_validation(self):
        v = vec(1)
        for args in (('', 's', 0, v), ('a', '', 0, v), ('a', 's', -1, v),
                     ('a', 's', True, v), ('a', 's', 1.0, v), (1, 's', 0, v)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Unit(*args)
        with self.assertRaises(TypeError):
            Unit('a', 's', 0, (1.0,))

    def test_deterministic_order_and_limit(self):
        units = [unit('a', 's1', 0, 1, 0), unit('b', 's2', 2, 1, 0),
                 unit('c', 's3', 4, 1, 0), unit('d', 's4', 6, 3, 4)]
        pairs = redundant_pairs(units, threshold=0.5)
        self.assertEqual([(p.first, p.second) for p in pairs],
                         [('a', 'b'), ('a', 'c'), ('b', 'c'),
                          ('a', 'd'), ('b', 'd'), ('c', 'd')])
        self.assertEqual(redundant_pairs(list(reversed(units)), threshold=0.5), pairs)
        self.assertEqual(redundant_pairs(units, threshold=0.5, limit=2), pairs[:2])

    def test_zero_vector_propagates(self):
        units = [unit('a', 's1', 0, 0, 0), unit('b', 's2', 2, 1, 0)]
        with self.assertRaises(ValueError):
            redundant_pairs(units)

    def test_empty(self):
        self.assertEqual(redundant_pairs([]), ())
        self.assertEqual(redundant_pairs(iter([])), ())


if __name__ == '__main__':
    unittest.main()

import itertools
import math
import unittest

from analysis.aggregate import AggregateLabel, SentenceLabel, aggregate, aggregate_section
from service.vectors import Level, LevelVector


def L(i, move, conf):
    return SentenceLabel(f's{i}', move, conf)


class AggregateTest(unittest.TestCase):
    def test_weight_beats_count(self):
        labels = [L(1, 'a', 0.2), L(2, 'a', 0.2), L(3, 'b', 0.9)]
        result = aggregate(labels, Level.BLOCK)
        self.assertEqual(result.move, 'b')
        self.assertAlmostEqual(result.confidence, 0.9 / 1.3)
        self.assertEqual(result.support, 3)
        self.assertIs(result.level, Level.BLOCK)

    def test_tie_broken_by_name(self):
        result = aggregate([L(1, 'zeta', 0.5), L(2, 'alpha', 0.5)], Level.SECTION)
        self.assertEqual(result.move, 'alpha')
        self.assertEqual([m for m, _ in result.distribution], ['alpha', 'zeta'])

    def test_empty(self):
        self.assertEqual(aggregate([], Level.BLOCK),
                         AggregateLabel(Level.BLOCK, None, 0.0, (), 0))

    def test_all_zero_falls_back_to_counts(self):
        result = aggregate([L(1, 'b', 0), L(2, 'a', 0.0), L(3, 'b', 0.0)], Level.BLOCK)
        self.assertEqual(result.move, 'b')
        self.assertAlmostEqual(result.confidence, 2 / 3)
        self.assertEqual(result.support, 3)

    def test_distribution_sums_to_one_and_sorted(self):
        labels = [L(1, 'c', 0.3), L(2, 'a', 0.3), L(3, 'b', 0.7), L(4, 'c', 0.1)]
        dist = aggregate(labels, Level.BLOCK).distribution
        self.assertAlmostEqual(math.fsum(w for _, w in dist), 1.0)
        self.assertEqual(dist, tuple(sorted(dist, key=lambda x: (-x[1], x[0]))))
        self.assertEqual([m for m, _ in dist], ['b', 'c', 'a'])

    def test_generator_input(self):
        gen = (L(i, 'a' if i % 2 else 'b', 0.5) for i in range(5))
        result = aggregate(gen, Level.BLOCK)
        self.assertEqual((result.move, result.support), ('b', 5))

    def test_sentence_level_rejected(self):
        with self.assertRaises(ValueError):
            aggregate([L(1, 'a', 1.0)], Level.SENTENCE)

    def test_level_vector_rejected(self):
        vec = LevelVector(Level.SENTENCE, (1.0, 0.0))
        with self.assertRaises(TypeError):
            aggregate([L(1, 'a', 1.0), vec], Level.BLOCK)
        with self.assertRaises(TypeError):
            aggregate(['a'], Level.BLOCK)
        with self.assertRaises(TypeError):
            aggregate_section([[vec]])

    def test_invalid_label_fields(self):
        for bad in (float('nan'), -0.1, 1.1, float('inf')):
            with self.assertRaises(ValueError):
                SentenceLabel('s', 'a', bad)
        with self.assertRaises(ValueError):
            SentenceLabel('', 'a', 0.5)
        with self.assertRaises(ValueError):
            SentenceLabel('s', '', 0.5)

    def test_section_pools_sentences(self):
        # Paragraph winners: a, a, b -> a paragraph vote would pick 'a'.
        paragraphs = [
            [L(1, 'a', 0.4), L(2, 'b', 0.3)],
            [L(3, 'a', 0.4), L(4, 'b', 0.3)],
            [L(5, 'b', 0.9)],
        ]
        winners = [aggregate(p, Level.BLOCK).move for p in paragraphs]
        self.assertEqual(winners, ['a', 'a', 'b'])
        result = aggregate_section(iter(paragraphs))
        self.assertEqual(result.move, 'b')
        self.assertEqual(result.support, 5)
        self.assertIs(result.level, Level.SECTION)

    def test_permutation_determinism(self):
        labels = [L(1, 'a', 0.1), L(2, 'b', 0.2), L(3, 'a', 0.2), L(4, 'c', 0.3),
                  L(5, 'b', 0.1)]
        results = {(r.move, r.distribution) for r in
                   (aggregate(p, Level.SECTION) for p in itertools.permutations(labels))}
        self.assertEqual(len(results), 1)


if __name__ == '__main__':
    unittest.main()

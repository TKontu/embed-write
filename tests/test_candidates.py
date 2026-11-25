"""Synthetic request-sized checks for GE-03; no model or corpus required."""

import unittest
from itertools import combinations

from generation import candidates
from generation.run_record import SamplingParams
from service.vectors import CrossLevelError, Level, LevelVector, cosine


def vector(*values, level=Level.BLOCK):
    return LevelVector(level, values)


class CandidateTests(unittest.TestCase):
    def test_sampling_is_distinct_bounded_and_repeatable(self):
        base = SamplingParams(42, 0.7, 0.9, 128)
        samples = candidates.vary_sampling(base, 8)
        self.assertEqual(len(samples), 8)
        self.assertEqual(len(set(samples)), 8)
        self.assertEqual(len({s.seed for s in samples}), 8)
        self.assertGreater(len({s.temperature for s in samples}), 1)
        self.assertTrue(all(0.2 <= s.temperature <= 1.0 for s in samples))
        self.assertTrue(all(s.top_p == base.top_p and s.max_tokens == base.max_tokens
                            for s in samples))
        self.assertEqual(samples, candidates.vary_sampling(base, 8))
        self.assertEqual(base, SamplingParams(42, 0.7, 0.9, 128))

    def test_single_sample_and_extreme_base_temperatures(self):
        for temperature in (-10.0, 0.0, 0.7, 100.0):
            samples = candidates.vary_sampling(SamplingParams(-2, temperature, 1.0, 1), 1)
            self.assertEqual(len(samples), 1)
            self.assertTrue(0.2 <= samples[0].temperature <= 1.0)

    def test_invalid_sample_counts(self):
        for n in (0, -1, True, 1.5, '2', None):
            with self.subTest(n=n), self.assertRaises(ValueError):
                candidates.vary_sampling(SamplingParams(1, 0.5, 1.0, 10), n)

    def test_greedy_order_first_cluster_member_and_pairwise_cutoff(self):
        texts = ['first', 'near', 'orthogonal', 'opposite', 'near orthogonal']
        vectors = [vector(1, 0), vector(1, 0.1), vector(0, 1),
                   vector(-1, 0), vector(0.1, 1)]
        kept = candidates.remove_near_duplicates(texts, vectors, 0.9)
        self.assertEqual(kept, ['first', 'orthogonal', 'opposite'])
        for a, b in combinations(kept, 2):
            self.assertLess(cosine(vectors[texts.index(a)], vectors[texts.index(b)]), 0.9)

    def test_only_kept_candidates_suppress_later_candidates(self):
        self.assertEqual(candidates.remove_near_duplicates(
            ['a', 'b', 'c'], [vector(1, 0), vector(1, 1), vector(0, 1)], 0.7),
            ['a', 'c'])

    def test_exact_text_duplicates_removed_even_with_different_vectors(self):
        self.assertEqual(candidates.remove_near_duplicates(
            ['same', 'same', 'other'], [vector(1, 0), vector(0, 1), vector(-1, 0)], 1),
            ['same', 'other'])

    def test_similarity_equal_to_cutoff_is_removed(self):
        self.assertEqual(candidates.remove_near_duplicates(
            ['a', 'b'], [vector(1, 0), vector(1, 0)], 1), ['a'])

    def test_empty_and_single_inputs(self):
        self.assertEqual(candidates.remove_near_duplicates([], [], 0.9), [])
        self.assertEqual(candidates.remove_near_duplicates(['a'], [vector(1, 0)], 0.9), ['a'])

    def test_invalid_cutoffs(self):
        for cutoff in (0, -0.1, 1.01, float('nan'), float('inf'), True, '0.9', None):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                candidates.remove_near_duplicates([], [], cutoff)

    def test_mismatched_lengths(self):
        for texts, vectors in ((['a'], []), ([], [vector(1, 0)])):
            with self.assertRaises(ValueError):
                candidates.remove_near_duplicates(texts, vectors, 0.9)

    def test_cross_level_rejected_even_for_duplicate_text_or_dropped_candidate(self):
        for texts in (['a', 'b', 'c'], ['a', 'a', 'a']):
            with self.assertRaises(CrossLevelError):
                candidates.remove_near_duplicates(texts, [vector(1, 0), vector(1, 0),
                    vector(1, 0, level=Level.SENTENCE)], 0.9)

    def test_invalid_vectors_rejected_even_for_singleton_or_duplicate(self):
        for texts, vectors in ((['a'], [vector(0, 0)]),
                               (['a', 'a'], [vector(1, 0), vector(1)])):
            with self.assertRaises(ValueError):
                candidates.remove_near_duplicates(texts, vectors, 0.9)

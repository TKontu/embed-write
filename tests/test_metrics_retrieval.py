"""LLM-built synthetic hand cases for MT-03 / MT-07; no corpus data."""

import importlib.util
import unittest


class RetrievalTests(unittest.TestCase):
    def test_recall_counts_relevant_ids_in_prefix(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.metrics.retrieval'))
        from experiments.metrics.retrieval import recall_at_k

        # Top 3 contain a and b: 2 of 4 relevant IDs = 1/2.
        self.assertEqual(recall_at_k(['a', 'x', 'b', 'c'], {'a', 'b', 'c', 'd'}, 3), 0.5)

    def test_recall_rejects_nonpositive_k(self):
        from experiments.metrics.retrieval import recall_at_k

        for k in (0, -1):
            with self.subTest(k=k), self.assertRaises(ValueError):
                recall_at_k(['a'], {'a'}, k)

    def test_recall_rejects_undefined_empty_relevance(self):
        from experiments.metrics.retrieval import recall_at_k

        with self.assertRaises(ValueError):
            recall_at_k(['a'], set(), 1)

    def test_short_empty_and_duplicate_rankings(self):
        from experiments.metrics.retrieval import recall_at_k

        # One of two relevant IDs = 1/2, even with k=5 or repeated hits.
        self.assertEqual(recall_at_k(['a'], {'a', 'b'}, 5), 0.5)
        self.assertEqual(recall_at_k(['a', 'a', 'b'], {'a', 'b'}, 2), 0.5)
        # No hits / two relevant = 0; two distinct hits / two = 1.
        self.assertEqual(recall_at_k([], {'a', 'b'}, 2), 0)
        self.assertEqual(recall_at_k(['x'], {'a', 'b'}, 2), 0)
        self.assertEqual(recall_at_k(['a', 'b'], {'a', 'b'}, 2), 1)

    def metric(self, name):
        from experiments.metrics import retrieval

        self.assertTrue(hasattr(retrieval, name), f'missing metric: {name}')
        return getattr(retrieval, name)

    def test_mean_recall_streams_and_skips_empty_relevance(self):
        mean_recall = self.metric('mean_recall_at_k')
        # Macro mean: (1/2 + 1/1 + 0/1) / 3 = 1/2; two skipped.
        queries = ((ranked, relevant) for ranked, relevant in [
            (['a'], {'a', 'b'}), (['x'], set()),
            (['c'], {'c'}), ([], {'d'}), ([], set()),
        ])
        self.assertEqual(mean_recall(queries, 3),
                         {'recall_at_k': 0.5, 'n': 3, 'skipped': 2})

    def test_mean_recall_rejects_empty_population(self):
        mean_recall = self.metric('mean_recall_at_k')
        for queries in (iter(()), iter([([], set())])):
            with self.assertRaises(ValueError):
                mean_recall(queries, 1)

    def test_means_reject_nonpositive_k_before_reading_queries(self):
        def unreadable():
            self.fail('invalid k must be rejected before reading queries')
            yield

        for name in ('mean_recall_at_k', 'mean_same_move_rate'):
            metric = self.metric(name)
            for k in (0, -2):
                with self.subTest(name=name, k=k), self.assertRaises(ValueError):
                    metric(unreadable(), k)

    def test_same_move_rate_uses_available_prefix(self):
        rate = self.metric('same_move_rate')
        # First two contain one match: 1/2; third matching label excluded.
        self.assertEqual(rate(['claim', 'evidence', 'claim'], 'claim', 2), 0.5)
        # With k=9, only two neighbours exist: 1/2, not 1/9.
        self.assertEqual(rate(['claim', 'evidence'], 'claim', 9), 0.5)
        # Each neighbour counts, even when move labels repeat: 2/2 = 1.
        self.assertEqual(rate(['claim', 'claim'], 'claim', 2), 1)
        self.assertEqual(rate(['evidence'], 'claim', 1), 0)  # 0/1
        self.assertEqual(rate([], 'claim', 3), 0)  # Empty retrieval convention.

    def test_same_move_rate_rejects_nonpositive_k(self):
        rate = self.metric('same_move_rate')
        for k in (0, -2):
            with self.subTest(k=k), self.assertRaises(ValueError):
                rate([], 'claim', k)

    def test_mean_same_move_is_query_weighted(self):
        mean_rate = self.metric('mean_same_move_rate')
        # Macro mean (1/2 + 1/1 + 0) / 3 = 1/2; empty retrieval included.
        queries = ((move, neighbours) for move, neighbours in [
            ('claim', ['claim', 'evidence']), ('evidence', ['evidence']),
            ('claim', []),
        ])
        self.assertEqual(mean_rate(queries, 5), {'rate': 0.5, 'n': 3})

    def test_mean_same_move_rejects_empty_population(self):
        mean_rate = self.metric('mean_same_move_rate')
        with self.assertRaises(ValueError):
            mean_rate(iter(()), 1)

    def test_means_process_each_query_before_advancing(self):
        class QuerySequence(list):
            visited = False

            def __getitem__(self, index):
                self.visited = True
                return super().__getitem__(index)

        def recall_queries():
            for _ in range(100):
                ranked = QuerySequence(['a'])
                yield ranked, {'a'}
                self.assertTrue(ranked.visited, 'queries were materialized')

        def move_queries():
            for _ in range(100):
                neighbours = QuerySequence(['claim'])
                yield 'claim', neighbours
                self.assertTrue(neighbours.visited, 'queries were materialized')

        # 100 perfect queries: sum 100 / count 100 = 1.
        self.assertEqual(self.metric('mean_recall_at_k')(recall_queries(), 1),
                         {'recall_at_k': 1, 'n': 100, 'skipped': 0})
        self.assertEqual(self.metric('mean_same_move_rate')(move_queries(), 1),
                         {'rate': 1, 'n': 100})

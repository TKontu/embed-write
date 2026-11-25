"""Synthetic LLM-built examples for the LY-06 cache contract."""

import unittest

from analysis import slow_cache
from analysis.signals import Signal


class SlowLayerCacheTests(unittest.TestCase):
    def cache(self, capacity=2):
        self.assertTrue(hasattr(slow_cache, 'SlowLayerCache'), 'cache API missing')
        return slow_cache.SlowLayerCache(capacity)

    def test_identical_pair_returns_original_signal(self):
        cache = self.cache()
        value = Signal('node', 'sentence', 'move', 'claim', .8, 'test',
                       'confirmed', '2026-11-25')
        cache.put('content', 'context', value)
        self.assertIs(cache.get('content', 'context'), value)

    def test_changed_context_misses(self):
        cache = self.cache()
        cache.put('content', 'old', object())
        self.assertIsNone(cache.get('content', 'new'))

    def test_changed_content_misses(self):
        cache = self.cache()
        cache.put('old', 'context', object())
        self.assertIsNone(cache.get('new', 'context'))

    def test_get_promotes_lru_and_counts_stats(self):
        cache = self.cache()
        cache.put('a', 'x', 1)
        cache.put('b', 'x', 2)
        self.assertEqual(cache.get('a', 'x'), 1)
        cache.put('c', 'x', 3)
        self.assertIsNone(cache.get('b', 'x'))
        self.assertEqual(cache.get('c', 'x'), 3)
        stats = cache.stats()
        self.assertEqual((stats.hits, stats.misses, stats.evictions, stats.size),
                         (2, 1, 1, 2))
        self.assertEqual(len(cache), 2)

    def test_overwrite_promotes_without_eviction(self):
        cache = self.cache()
        cache.put('a', 'x', 1)
        cache.put('b', 'x', 2)
        cache.put('a', 'x', 3)
        self.assertEqual(cache.stats().evictions, 0)
        cache.put('c', 'x', 4)
        self.assertIsNone(cache.get('b', 'x'))
        self.assertEqual(cache.get('a', 'x'), 3)
        self.assertEqual(cache.stats().evictions, 1)

    def test_invalidate_drops_all_contexts_only_for_content(self):
        cache = self.cache(3)
        cache.put('a', 'x', 1)
        cache.put('a', 'y', 2)
        cache.put('b', 'x', 3)
        cache.invalidate_content('a')
        cache.invalidate_content('absent')
        self.assertIsNone(cache.get('a', 'x'))
        self.assertIsNone(cache.get('a', 'y'))
        self.assertEqual(cache.get('b', 'x'), 3)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.stats().evictions, 0)

    def test_invalidate_after_eviction_and_reinsert(self):
        cache = self.cache()
        cache.put('a', 'x', 1)
        cache.put('a', 'y', 2)
        cache.put('b', 'x', 3)
        cache.invalidate_content('a')
        cache.put('a', 'x', 4)
        cache.invalidate_content('a')
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.get('b', 'x'), 3)

    def test_clear_preserves_counters_and_allows_reuse(self):
        cache = self.cache(1)
        cache.put('a', 'x', 1)
        cache.get('a', 'x')
        cache.put('b', 'x', 2)
        cache.get('a', 'x')
        snapshot = cache.stats()
        cache.clear()
        cache.clear()
        self.assertEqual(len(cache), 0)
        stats = cache.stats()
        self.assertEqual((stats.hits, stats.misses, stats.evictions, stats.size),
                         (1, 1, 1, 0))
        self.assertEqual(snapshot.size, 1)
        cache.invalidate_content('b')
        cache.put('b', 'x', 3)
        self.assertEqual(cache.get('b', 'x'), 3)

    def test_opaque_falsey_values_are_hits(self):
        cache = self.cache()
        for value in (None, False, 0, [], {}):
            cache.put('a', 'x', value)
            self.assertIs(cache.get('a', 'x'), value)
        self.assertEqual(cache.stats().hits, 5)
        self.assertEqual(cache.stats().misses, 0)

    def test_invalid_hashes_do_not_mutate_cache_or_stats(self):
        cache = self.cache()
        cache.put('a', 'x', 1)
        before = cache.stats()
        for bad in (None, 1, False, b'hash', [], ''):
            error = ValueError if bad == '' else TypeError
            for operation in (lambda: cache.get(bad, 'x'),
                              lambda: cache.get('a', bad),
                              lambda: cache.put(bad, 'x', 2),
                              lambda: cache.put('a', bad, 2),
                              lambda: cache.invalidate_content(bad)):
                with self.subTest(bad=bad, operation=operation):
                    with self.assertRaises(error):
                        operation()
                    self.assertEqual(cache.stats(), before)
        self.assertEqual(cache.get('a', 'x'), 1)

    def test_invalid_capacity(self):
        for capacity in (0, -1, True, False, 1.5, '2', None):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    self.cache(capacity)


if __name__ == '__main__':
    unittest.main()

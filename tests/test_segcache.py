"""CK-03 segmentation cache tests with a counting fake segmenter."""

import unittest

from service.contract import node_hash
from service.segcache import CacheStats, SegmentationCache


class Counting:
    def __init__(self, output=None):
        self.calls = 0
        self.output = output

    def __call__(self, text):
        self.calls += 1
        return self.output if self.output is not None else text.split(". ")


class SegCacheTests(unittest.TestCase):
    def test_hit_avoids_call(self):
        seg = Counting(); c = SegmentationCache(seg, 4)
        self.assertEqual(c.get("A. B"), ("A", "B"))
        self.assertEqual(c.get("A. B"), ("A", "B"))
        self.assertEqual(seg.calls, 1)

    def test_different_text_misses(self):
        seg = Counting(); c = SegmentationCache(seg, 4)
        c.get("A"); c.get("B")
        self.assertEqual(seg.calls, 2)

    def test_identical_text_shares_entry(self):
        seg = Counting(); c = SegmentationCache(seg, 4)
        blocks = {"b1": "Same. Text", "b2": "Same. Text"}
        for text in blocks.values():
            c.get(text)
        self.assertEqual((seg.calls, len(c)), (1, 1))

    def test_lru_at_cap_and_over(self):
        seg = Counting(); c = SegmentationCache(seg, 2)
        c.get("a"); c.get("b")
        self.assertEqual(c.stats(), CacheStats(0, 2, 0, 2))
        c.get("c")
        self.assertEqual(c.stats(), CacheStats(0, 3, 1, 2))
        c.get("b"); c.get("c")
        self.assertEqual(seg.calls, 3)
        c.get("a")
        self.assertEqual(seg.calls, 4)

    def test_hit_refreshes_recency(self):
        seg = Counting(); c = SegmentationCache(seg, 2)
        c.get("a"); c.get("b"); c.get("a"); c.get("c")
        c.get("a")
        self.assertEqual(seg.calls, 3)
        c.get("b")
        self.assertEqual(seg.calls, 4)

    def test_bad_output(self):
        for bad in ([1, 2], "abc", 5, ["ok", None]):
            seg = Counting(); seg.output = bad
            c = SegmentationCache(seg, 2)
            with self.assertRaises(TypeError):
                c.get("x")
            self.assertEqual(len(c), 0)

    def test_invalid_args(self):
        for bad in (0, -1, 1.5, True, "2"):
            with self.assertRaises(ValueError):
                SegmentationCache(Counting(), bad)
        with self.assertRaises(TypeError):
            SegmentationCache("nope", 2)

    def test_immutable(self):
        c = SegmentationCache(Counting(output=["a", "b"]), 2)
        r = c.get("x")
        self.assertIsInstance(r, tuple)
        with self.assertRaises(TypeError):
            r[0] = "z"

    def test_key_version_change_misses(self):
        seg = Counting()
        c1 = SegmentationCache(seg, 2, key_version="v1")
        c2 = SegmentationCache(seg, 2, key_version="v2")
        c1.get("x"); c2.get("x")
        self.assertEqual(seg.calls, 2)
        self.assertNotEqual(c1._key("h"), c2._key("h"))

    def test_invalidate_and_clear(self):
        seg = Counting(); c = SegmentationCache(seg, 4)
        c.get("x"); c.get("y")
        c.invalidate(node_hash("x"))
        c.invalidate("missing")
        self.assertEqual(len(c), 1)
        c.get("x")
        self.assertEqual(seg.calls, 3)
        c.clear()
        self.assertEqual(c.stats().size, 0)

    def test_stats(self):
        c = SegmentationCache(Counting(), 1)
        c.get("a"); c.get("a"); c.get("b")
        self.assertEqual(c.stats(), CacheStats(hits=1, misses=2, evictions=1, size=1))


if __name__ == "__main__":
    unittest.main()

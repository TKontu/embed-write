"""DS-02: expert corrections outrank slow-layer labels, which outrank nothing."""

import copy
import unittest

from analysis.label_precedence import SOURCES, resolve_labels


def slow(node, label, ts=None, mv="slow-v1"):
    c = {"node_id": node, "label": label, "source": "slow_layer", "model_version": mv}
    if ts is not None:
        c["timestamp"] = ts
    return c


def expert(node, label, ts=None):
    c = {"node_id": node, "label": label, "source": "expert", "model_version": None}
    if ts is not None:
        c["timestamp"] = ts
    return c


class LabelPrecedenceTest(unittest.TestCase):
    def test_sources_ranked(self):
        self.assertEqual(SOURCES, ("expert", "slow_layer"))

    def test_expert_beats_slow_regardless_of_order_and_timestamp(self):
        e = expert("n1", "unsupported", ts=1)
        s = slow("n1", "supported", ts=100)
        self.assertIs(resolve_labels([e, s])["n1"], e)
        self.assertIs(resolve_labels([s, e])["n1"], e)

    def test_slow_alone_wins(self):
        s = slow("n2", "supported")
        self.assertEqual(resolve_labels([s]), {"n2": s})

    def test_latest_within_source(self):
        a, b = slow("n", "x", ts=5), slow("n", "y", ts=3.5)
        self.assertIs(resolve_labels([a, b])["n"], a)
        self.assertIs(resolve_labels([b, a])["n"], a)
        e1, e2 = expert("n", "p", ts=2), expert("n", "q", ts=9)
        self.assertIs(resolve_labels([e2, e1])["n"], e2)

    def test_tie_by_position(self):
        a, b = slow("n", "x", ts=5), slow("n", "y", ts=5)
        self.assertIs(resolve_labels([a, b])["n"], b)
        c, d = expert("n", "x"), expert("n", "y")
        self.assertIs(resolve_labels([c, d])["n"], d)

    def test_empty_and_absent_nodes(self):
        self.assertEqual(resolve_labels([]), {})
        self.assertNotIn("n9", resolve_labels([slow("n1", "x")]))

    def test_errors_name_index(self):
        bad = [
            {"label": "x", "source": "expert"},
            {"node_id": "n", "source": "expert"},
            {"node_id": "n", "label": "x", "source": "crowd"},
            {"node_id": "n", "label": "x", "source": "slow_layer"},
            slow("n", "x", mv=""),
            slow("n", "x", mv=3),
        ]
        for b in bad:
            with self.subTest(b=b):
                with self.assertRaisesRegex(ValueError, r"\b1\b"):
                    resolve_labels([expert("ok", "y"), b])

    def test_bad_timestamp_rejected(self):
        for ts in ("5", True):
            with self.assertRaisesRegex(ValueError, r"\b0\b"):
                resolve_labels([slow("n", "x", ts=ts)])

    def test_generator_input(self):
        gen = (slow(f"n{i}", "x", ts=i) for i in range(3))
        self.assertEqual(sorted(resolve_labels(gen)), ["n0", "n1", "n2"])

    def test_inputs_unchanged(self):
        items = [slow("n", "x", ts=1), expert("n", "y")]
        before = copy.deepcopy(items)
        resolve_labels(items)
        self.assertEqual(items, before)


if __name__ == "__main__":
    unittest.main()

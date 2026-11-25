"""State-machine checks using synthetic LLM-built signals."""

import unittest
from dataclasses import replace

from analysis.reconcile_layers import LayerReconciler
from analysis.signals import Signal


def signal(layer="provisional", **changes):
    return replace(Signal("n1", "sentence", "move", "claim", 0.8,
                          "synthetic", layer, "2026-11-25T00:00:00Z"), **changes)


class LayerReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.store = LayerReconciler()
        self.key = ("n1", "sentence", "move")

    def test_empty(self):
        self.assertIsNone(self.store.current(*self.key))
        self.assertEqual(self.store.state(*self.key), "empty")

    def test_set_provisional(self):
        item = signal()
        self.assertEqual(self.store.offer(item, "a"), "set_provisional")
        self.assertIs(self.store.current(*self.key), item)

    def test_replace_provisional(self):
        self.store.offer(signal(), "a")
        item = signal(value="replacement")
        self.assertEqual(self.store.offer(item, "a"), "replace_provisional")
        self.assertIs(self.store.current(*self.key), item)

    def test_confirm(self):
        self.store.offer(signal(), "a")
        item = signal("confirmed")
        self.assertEqual(self.store.offer(item, "a"), "confirm")
        self.assertIs(self.store.current(*self.key), item)

    def test_replace_confirmed(self):
        self.store.offer(signal("confirmed"), "a")
        item = signal("confirmed", value="replacement")
        self.assertEqual(self.store.offer(item, "a"), "replace_confirmed")
        self.assertIs(self.store.current(*self.key), item)

    def test_ignored_provisional(self):
        item = signal("confirmed")
        self.store.offer(item, "a")
        self.assertEqual(self.store.offer(signal(), "a"), "ignored_provisional")
        self.assertIs(self.store.current(*self.key), item)

    def test_full_transition_table_preserves_layers(self):
        # Different content starts from empty, regardless of the old layer.
        table = {
            ("empty", "provisional"): "set_provisional",
            ("empty", "confirmed"): "confirm",
            ("provisional", "provisional"): "replace_provisional",
            ("provisional", "confirmed"): "confirm",
            ("confirmed", "provisional"): "ignored_provisional",
            ("confirmed", "confirmed"): "replace_confirmed",
        }
        for old in ("empty", "provisional", "confirmed"):
            for incoming in ("provisional", "confirmed"):
                for same_hash in (False, True):
                    with self.subTest(old=old, incoming=incoming, same_hash=same_hash):
                        store = LayerReconciler()
                        previous = signal(old) if old != "empty" else None
                        if previous is not None:
                            store.offer(previous, "a")
                        item = signal(incoming, value="new")
                        expected = table[(old if same_hash else "empty", incoming)]
                        self.assertEqual(store.offer(item, "a" if same_hash else "b"), expected)
                        kept = previous if expected == "ignored_provisional" else item
                        self.assertIs(store.current(*self.key), kept)
                        self.assertEqual(store.state(*self.key), kept.layer)
                        self.assertEqual(item.layer, incoming)
                        if previous is not None:
                            self.assertEqual(previous.layer, old)

    def test_keys_are_independent(self):
        items = [signal(), signal(node_id="n2"), signal(level="paragraph"),
                 signal(kind="support")]
        for item in items:
            self.store.offer(item, "a")
        for item in items:
            self.assertIs(self.store.current(item.node_id, item.level, item.kind), item)

    def test_invalidate_drops_only_changed_hashes_for_node(self):
        stale = [signal("confirmed"), signal(level="paragraph")]
        kept = [signal(kind="support"), signal(node_id="n2")]
        for item in stale:
            self.store.offer(item, "a")
        self.store.offer(kept[0], "b")
        self.store.offer(kept[1], "a")
        self.store.invalidate("n1", "b")
        self.store.invalidate("unknown", "b")
        for item in stale:
            key = (item.node_id, item.level, item.kind)
            self.assertIsNone(self.store.current(*key))
            self.assertEqual(self.store.state(*key), "empty")
        for item in kept:
            self.assertIs(self.store.current(item.node_id, item.level, item.kind), item)
        self.assertEqual(self.store.offer(signal(), "b"), "set_provisional")

    def test_rejects_non_signal_without_mutation(self):
        for value in (None, {}, "signal", 1):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.store.offer(value, "a")
        self.assertEqual(self.store.state(*self.key), "empty")

    def test_rejects_invalid_hash_without_mutation(self):
        item = signal("confirmed")
        self.store.offer(item, "a")
        for value, error in (("", ValueError), (None, TypeError), (1, TypeError)):
            for operation in (lambda: self.store.offer(signal(), value),
                              lambda: self.store.invalidate("n1", value)):
                with self.subTest(value=value), self.assertRaises(error):
                    operation()
                self.assertIs(self.store.current(*self.key), item)


if __name__ == "__main__":
    unittest.main()

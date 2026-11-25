"""DS-01 candidate label store tests. Synthetic LLM-built data only."""

import os
import tempfile
import types
import unittest

from analysis.label_precedence import resolve_labels
from analysis.label_store import CandidateLabelStore


class CandidateLabelStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "labels.jsonl")
        self.store = CandidateLabelStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def _raw(self):
        if not os.path.exists(self.path):
            return None
        with open(self.path, "rb") as fh:
            return fh.read()

    def test_round_trip(self):
        self.store.append("n1", "claim", "slow-v1", 10)
        self.assertEqual(
            list(self.store.iter_candidates()),
            [{"node_id": "n1", "label": "claim", "source": "slow_layer",
              "model_version": "slow-v1", "timestamp": 10}],
        )

    def test_order_preserved_and_duplicates_kept(self):
        self.store.append("n1", "claim", "v1", 1)
        self.store.append("n2", "évidence", "v1", 2.5)
        self.store.append("n1", "claim", "v1", 1)
        out = list(self.store.iter_candidates())
        self.assertEqual([r["node_id"] for r in out], ["n1", "n2", "n1"])
        self.assertEqual(out[0], out[2])
        self.assertEqual(out[1]["label"], "évidence")

    def test_invalid_inputs_leave_file_unchanged(self):
        bad = [
            ("", "l", "v", 1), (None, "l", "v", 1), (1, "l", "v", 1),
            ("n", "", "v", 1), ("n", None, "v", 1), ("n", 3, "v", 1),
            ("n", "l", "", 1), ("n", "l", None, 1), ("n", "l", 2, 1),
            ("n", "l", "v", True), ("n", "l", "v", "1"), ("n", "l", "v", None),
            ("n", "l", "v", float("nan")), ("n", "l", "v", float("inf")),
        ]
        for args in bad:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.store.append(*args)
                self.assertIsNone(self._raw())
        self.store.append("n", "l", "v", 1)
        before = self._raw()
        for args in bad:
            with self.subTest(after=args):
                with self.assertRaises(ValueError):
                    self.store.append(*args)
                self.assertEqual(self._raw(), before)

    def test_missing_file_yields_nothing(self):
        self.assertEqual(list(self.store.iter_candidates()), [])

    def test_malformed_line_names_line_number(self):
        self.store.append("n1", "l", "v", 1)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"node_id": "n2", "lab')
        it = self.store.iter_candidates()
        self.assertEqual(next(it)["node_id"], "n1")
        with self.assertRaisesRegex(ValueError, "line 2"):
            next(it)

    def test_non_object_line_rejected(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2]\n")
        with self.assertRaisesRegex(ValueError, "line 1"):
            list(self.store.iter_candidates())

    def test_iter_candidates_is_generator(self):
        self.assertIsInstance(self.store.iter_candidates(), types.GeneratorType)

    def test_resolve_labels_accepts_records_and_expert_wins(self):
        self.store.append("n1", "slow", "v1", 5)
        self.store.append("n2", "slow2", "v1", 5)
        expert = {"node_id": "n1", "label": "expert", "source": "expert", "timestamp": 1}

        def chained():
            yield from self.store.iter_candidates()
            yield expert

        winners = resolve_labels(chained())
        self.assertIs(winners["n1"], expert)
        self.assertEqual(winners["n2"]["label"], "slow2")


if __name__ == "__main__":
    unittest.main()

"""Synthetic document split enforcement checks."""
import random
import unittest

from experiments import splits


class SplitTests(unittest.TestCase):
    def make_split(self, train, test):
        self.assertTrue(callable(getattr(splits, "DocumentSplit", None)),
                        "DocumentSplit API is missing")
        return splits.DocumentSplit(train, test)

    def split_documents(self, ids, fraction, seed):
        self.assertTrue(callable(getattr(splits, "split_documents", None)),
                        "split_documents API is missing")
        return splits.split_documents(ids, fraction, seed)

    def test_training_id_fails_and_names_first_leak(self):
        split = self.make_split(["train-first", "train-second"], ["test"])
        with self.assertRaisesRegex(splits.SplitLeakError, "train-first"):
            split.check_eval(iter(["test", "train-first", "train-second"]))

    def test_unknown_id_fails_and_names_id(self):
        split = self.make_split(["train"], ["test"])
        with self.assertRaisesRegex(splits.SplitLeakError, "unknown"):
            split.check_eval(iter(["test", "unknown"]))

    def test_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            self.make_split(["same"], ["same"])

    def test_empty_test_set_is_rejected(self):
        with self.assertRaises(ValueError):
            self.make_split(["train"], [])

    def test_empty_train_and_empty_evaluation_are_allowed(self):
        split = self.make_split([], ["test"])
        self.assertIsNone(split.check_eval(iter(())))
        self.assertIsNone(split.check_eval(iter(["test", "test"])))

    def test_membership_is_an_immutable_snapshot(self):
        train, test = {"train"}, {"test"}
        split = self.make_split(train, test)
        train.add("test")
        test.clear()
        self.assertEqual(split.train_ids, frozenset({"train"}))
        self.assertEqual(split.test_ids, frozenset({"test"}))
        with self.assertRaises(AttributeError):
            split.train_ids = frozenset({"test"})

    def test_stops_consuming_immediately_at_leak(self):
        split = self.make_split(["train"], ["test"])

        def ids():
            yield "test"
            yield "train"
            self.fail("evaluation consumed beyond the first leak")

        with self.assertRaisesRegex(splits.SplitLeakError, "train"):
            split.check_eval(ids())

    def test_checks_100000_ids_from_generator(self):
        split = self.make_split([], (str(i) for i in range(100_000)))
        self.assertIsNone(split.check_eval(str(i) for i in range(100_000)))

    def test_split_is_deterministic_and_order_independent(self):
        ids = [str(i) for i in range(100)]
        first = self.split_documents(ids, 0.2, 42)
        second = self.split_documents(iter(ids), 0.2, 42)
        random.Random(9).shuffle(ids)
        shuffled = self.split_documents(ids, 0.2, 42)
        self.assertEqual(first, second)
        self.assertEqual(first, shuffled)
        self.assertEqual(len(first.test_ids), 20)
        self.assertEqual(len(first.train_ids), 80)
        self.assertFalse(first.train_ids & first.test_ids)
        self.assertEqual(first.train_ids | first.test_ids, set(ids))

    def test_duplicates_do_not_change_document_split(self):
        self.assertEqual(self.split_documents(["a", "b", "c"], 0.5, 1),
                         self.split_documents(["c", "a", "b", "a"], 0.5, 1))

    def test_small_fraction_keeps_at_least_one_test_document(self):
        split = self.split_documents(["a", "b"], 0.01, 1)
        self.assertEqual(len(split.test_ids), 1)
        self.assertEqual(len(split.train_ids), 1)
        self.assertEqual(self.split_documents(["a"], 0.2, 1).test_ids, {"a"})

    def test_invalid_fraction_and_empty_input_are_rejected(self):
        for fraction in (0, 1, -0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                self.split_documents(["a", "b"], fraction, 1)
        with self.assertRaises(ValueError):
            self.split_documents([], 0.2, 1)

    def test_split_does_not_change_global_rng(self):
        before = random.getstate()
        self.split_documents(["a", "b", "c"], 0.5, 1)
        self.assertEqual(random.getstate(), before)

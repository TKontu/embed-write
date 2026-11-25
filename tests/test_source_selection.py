import math
import unittest

from service.source_items import Provenance, SourceItem
from service.source_selection import (
    MoveRequest,
    MoveSelection,
    Selected,
    lexical_score,
    select_sources,
)

_PROV = Provenance(source="synthetic", locator=None, recorded_by="test", recorded_at=None)


def item(item_id, content="alpha"):
    return SourceItem(id=item_id, type="observation", content=content, units=(), provenance=_PROV)


def table(scores):
    """Scorer from {(query, item_id): score}; missing pairs score 0.0."""
    return lambda q, it: scores.get((q, it.id), 0.0)


class SelectSourcesTest(unittest.TestCase):
    def test_two_moves_sorted_ties_by_input_order(self):
        items = [item("a"), item("b"), item("c"), item("d")]
        score = table({("q1", "a"): 0.2, ("q1", "b"): 0.9, ("q1", "c"): 0.2,
                       ("q2", "d"): 0.7, ("q2", "a"): 0.5})
        rep = select_sources([MoveRequest("m1", "q1"), MoveRequest("m2", "q2")], items, score,
                             k=3, min_score=0.1)
        self.assertEqual(rep.moves[0], MoveSelection(
            "m1", (Selected("b", 0.9), Selected("a", 0.2), Selected("c", 0.2))))
        self.assertEqual(rep.moves[1], MoveSelection(
            "m2", (Selected("d", 0.7), Selected("a", 0.5))))

    def test_k_caps_and_ties_keep_first(self):
        items = [item(x) for x in "abcde"]
        rep = select_sources([MoveRequest("m", "q")], items, lambda q, it: 1.0, k=2)
        self.assertEqual([s.item_id for s in rep.moves[0].selected], ["a", "b"])

    def test_min_score_and_empty_moves(self):
        items = [item("a"), item("b")]
        score = table({("q1", "a"): 0.6, ("q1", "b"): 0.3, ("q2", "a"): 0.1})
        rep = select_sources([MoveRequest("m1", "q1"), MoveRequest("m2", "q2")], items, score,
                             min_score=0.5)
        self.assertEqual(rep.moves[0].selected, (Selected("a", 0.6),))
        self.assertEqual(rep.moves[1], MoveSelection("m2", ()))
        self.assertEqual(rep.empty_moves, ("m2",))
        self.assertEqual([m.move for m in rep.moves], ["m1", "m2"])

    def test_unused_ids_in_input_order(self):
        items = [item("z"), item("a"), item("y"), item("b")]
        score = table({("q", "a"): 1.0, ("q", "b"): 1.0})
        rep = select_sources([MoveRequest("m", "q")], items, score, min_score=0.5)
        self.assertEqual(rep.unused_ids, ("z", "y"))

    def test_generator_iterated_once(self):
        calls = []

        def gen():
            calls.append(1)
            yield item("a")
            yield item("b")

        g = gen()
        rep = select_sources([MoveRequest("m1", "q"), MoveRequest("m2", "q")], g,
                             lambda q, it: 1.0)
        self.assertEqual(calls, [1])
        self.assertEqual(list(g), [])
        self.assertEqual(len(rep.moves[1].selected), 2)

    def test_errors(self):
        ok = [MoveRequest("m", "q")]
        one = lambda q, it: 1.0
        for kwargs in ({"k": 0}, {"k": -1}):
            with self.assertRaises(ValueError):
                select_sources(ok, [item("a")], one, **kwargs)
        for bad in ([MoveRequest(" ", "q")], [MoveRequest("m", "")], [MoveRequest("m", "\t")],
                    [MoveRequest("m", "q"), MoveRequest("m", "r")]):
            with self.assertRaises(ValueError):
                select_sources(bad, [item("a")], one)
        with self.assertRaises(ValueError):
            select_sources(ok, [item("a"), item("a")], one)
        for val in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                select_sources(ok, [item("a")], lambda q, it, v=val: v)
        with self.assertRaises(TypeError):
            select_sources([("m", "q")], [item("a")], one)
        with self.assertRaises(TypeError):
            select_sources(ok, ["a"], one)


class LexicalScoreTest(unittest.TestCase):
    def test_scores(self):
        it = item("a", "The beam deflected 12 mm under load.")
        self.assertEqual(lexical_score("beam LOAD", it), 1.0)
        self.assertEqual(lexical_score("beam crack beam", it), 0.5)
        self.assertEqual(lexical_score("crack", it), 0.0)
        self.assertEqual(lexical_score("  ...  ", it), 0.0)
        self.assertEqual(lexical_score("", it), 0.0)


if __name__ == "__main__":
    unittest.main()

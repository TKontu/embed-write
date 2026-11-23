import unittest

from service.dirty import Hierarchy, NodeRef, dirty_set
from service.vectors import Level

S, B, X = Level.SENTENCE, Level.BLOCK, Level.SECTION


def _nodes():
    return [
        NodeRef('x1', X, None), NodeRef('x2', X, None),
        NodeRef('b1', B, 'x1'), NodeRef('b2', B, 'x1'), NodeRef('b3', B, 'x2'),
        NodeRef('s1', S, 'b1'), NodeRef('s2', S, 'b1'), NodeRef('s3', S, 'b2'),
        NodeRef('s4', S, 'b3'),
    ]


def _expect(s=(), b=(), x=()):
    return {S: frozenset(s), B: frozenset(b), X: frozenset(x)}


class DirtySetTest(unittest.TestCase):
    def setUp(self):
        self.h = Hierarchy.from_nodes(_nodes())

    def test_sentence_dirties_block_and_section_only(self):
        self.assertEqual(dirty_set(self.h, ['s1']), _expect(['s1'], ['b1'], ['x1']))

    def test_block_dirties_section_only(self):
        self.assertEqual(dirty_set(self.h, ['b2']), _expect([], ['b2'], ['x1']))

    def test_section_dirties_itself(self):
        self.assertEqual(dirty_set(self.h, ['x2']), _expect([], [], ['x2']))

    def test_union(self):
        self.assertEqual(dirty_set(self.h, ['s1', 's2', 's4', 'b2']),
                         _expect(['s1', 's2', 's4'], ['b1', 'b2', 'b3'], ['x1', 'x2']))

    def test_empty(self):
        self.assertEqual(dirty_set(self.h, []), _expect())

    def test_deterministic(self):
        self.assertEqual(dirty_set(self.h, ['s3', 's1']), dirty_set(self.h, ['s1', 's3']))

    def test_unknown_changed_id(self):
        with self.assertRaises(KeyError):
            dirty_set(self.h, ['nope'])


class HierarchyValidationTest(unittest.TestCase):
    def test_duplicate(self):
        with self.assertRaises(ValueError):
            Hierarchy.from_nodes([NodeRef('x', X, None), NodeRef('x', X, None)])

    def test_unknown_parent(self):
        with self.assertRaises(ValueError):
            Hierarchy.from_nodes([NodeRef('b', B, 'missing')])

    def test_forward_parent_reference_ok(self):
        h = Hierarchy.from_nodes([NodeRef('s', S, 'b'), NodeRef('b', B, 'x'),
                                  NodeRef('x', X, None)])
        self.assertEqual(len(h), 3)

    def test_wrong_parent_level(self):
        with self.assertRaises(ValueError):
            Hierarchy.from_nodes([NodeRef('x', X, None), NodeRef('s', S, 'x')])
        with self.assertRaises(ValueError):
            Hierarchy.from_nodes([NodeRef('x', X, None), NodeRef('b', B, 'x'),
                                  NodeRef('b2', B, 'b')])

    def test_missing_parent_for_child_level(self):
        with self.assertRaises(ValueError):
            Hierarchy.from_nodes([NodeRef('b', B, None)])

    def test_section_with_parent(self):
        with self.assertRaises(ValueError):
            Hierarchy.from_nodes([NodeRef('x', X, None), NodeRef('y', X, 'x')])

    def test_empty_node_id(self):
        with self.assertRaises(ValueError):
            NodeRef('', X, None)

    def test_empty_parent_id(self):
        with self.assertRaises(ValueError):
            NodeRef('b', B, '')

    def test_non_level(self):
        with self.assertRaises(TypeError):
            NodeRef('x', 'section', None)

    def test_generator_consumed_once(self):
        calls = []

        def gen():
            calls.append(1)
            yield from _nodes()

        h = Hierarchy.from_nodes(gen())
        self.assertEqual(calls, [1])
        self.assertEqual(len(h), 9)
        self.assertEqual(dirty_set(h, ['s4']), _expect(['s4'], ['b3'], ['x2']))


if __name__ == '__main__':
    unittest.main()

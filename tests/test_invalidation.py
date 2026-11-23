import unittest

from analysis.invalidation import DirtyRequest, affected_signals
from analysis.signals import Signal
from service.dirty import Hierarchy, NodeRef
from service.vectors import Level

S, B, X = Level.SENTENCE, Level.BLOCK, Level.SECTION


def _hierarchy():
    return Hierarchy.from_nodes([
        NodeRef('x1', X, None), NodeRef('x2', X, None),
        NodeRef('b1', B, 'x1'), NodeRef('b2', B, 'x1'), NodeRef('b3', B, 'x2'),
        NodeRef('s1', S, 'b1'), NodeRef('s2', S, 'b1'), NodeRef('s3', S, 'b2'),
        NodeRef('s4', S, 'b3'),
    ])


def _sig(node_id, level):
    return Signal(node_id, level, 'move', 'm', 0.5, 'ref', 'provisional', 't0')


OLD = {k: 'h-' + k for k in ('x1', 'x2', 'b1', 'b2', 'b3', 's1', 's2', 's3', 's4')}


def _signals():
    return [_sig('s1', 'sentence'), _sig('s2', 'sentence'), _sig('b1', 'block'),
            _sig('b2', 'block'), _sig('x1', 'section'), _sig('x2', 'section'),
            _sig('s4', 'sentence')]


def _ids(sigs):
    return [s.node_id for s in sigs]


class AffectedSignalsTest(unittest.TestCase):
    def setUp(self):
        self.h = _hierarchy()

    def test_sentence_change_marks_ancestors_keeps_siblings(self):
        r = affected_signals(self.h, OLD, DirtyRequest(frozenset({'s1'}), {'s1': 'new'}),
                             _signals())
        self.assertEqual(_ids(r.affected), ['s1', 'b1', 'x1'])
        self.assertEqual(_ids(r.kept), ['s2', 'b2', 'x2', 's4'])
        self.assertEqual(r.dirty[S], frozenset({'s1'}))
        self.assertEqual(r.hashes['s1'], 'new')

    def test_unchanged_hash_is_noop(self):
        r = affected_signals(self.h, OLD, DirtyRequest(frozenset({'s1'}), {'s1': 'h-s1'}),
                             _signals())
        self.assertEqual(r.affected, ())
        self.assertEqual(len(r.kept), 7)
        self.assertTrue(all(not ids for ids in r.dirty.values()))
        self.assertEqual(dict(r.hashes), OLD)

    def test_mixed_changed_and_noop(self):
        req = DirtyRequest(frozenset({'s1', 's4'}), {'s1': 'h-s1', 's4': 'new'})
        r = affected_signals(self.h, OLD, req, _signals())
        self.assertEqual(_ids(r.affected), ['x2', 's4'])
        self.assertEqual(r.hashes['s4'], 'new')
        self.assertEqual(r.hashes['s1'], 'h-s1')

    def test_new_node_without_old_hash_is_dirty(self):
        old = {k: v for k, v in OLD.items() if k != 's3'}
        r = affected_signals(self.h, old, DirtyRequest(frozenset({'s3'}), {'s3': 'n'}), [])
        self.assertEqual(r.dirty[B], frozenset({'b2'}))
        self.assertEqual(r.hashes['s3'], 'n')

    def test_request_validation(self):
        with self.assertRaises(ValueError):
            DirtyRequest(frozenset({'s1'}), {})
        with self.assertRaises(ValueError):
            DirtyRequest(frozenset({'s1'}), {'s1': 'a', 's2': 'b'})
        with self.assertRaises(ValueError):
            DirtyRequest(frozenset({'s1'}), {'s1': ''})
        with self.assertRaises(ValueError):
            DirtyRequest(frozenset({'s1'}), {'s1': 3})

    def test_request_hashes_immutable_copy(self):
        src = {'s1': 'a'}
        req = DirtyRequest(frozenset({'s1'}), src)
        src['s1'] = 'b'
        self.assertEqual(req.new_hashes['s1'], 'a')
        with self.assertRaises(TypeError):
            req.new_hashes['s1'] = 'c'

    def test_unknown_id_keyerror(self):
        with self.assertRaises(KeyError):
            affected_signals(self.h, OLD, DirtyRequest(frozenset({'zz'}), {'zz': 'n'}), [])

    def test_order_preserved(self):
        sigs = list(reversed(_signals()))
        r = affected_signals(self.h, OLD, DirtyRequest(frozenset({'s1'}), {'s1': 'n'}), sigs)
        self.assertEqual(_ids(r.affected), ['x1', 'b1', 's1'])
        self.assertEqual(_ids(r.kept), ['s4', 'x2', 'b2', 's2'])

    def test_inputs_not_mutated(self):
        old = dict(OLD)
        sigs = _signals()
        r = affected_signals(self.h, old, DirtyRequest(frozenset({'s1'}), {'s1': 'n'}), sigs)
        self.assertEqual(old, OLD)
        self.assertEqual(len(sigs), 7)
        with self.assertRaises(TypeError):
            r.hashes['s1'] = 'x'

    def test_generator_consumed_once(self):
        calls = []

        def gen():
            calls.append(1)
            yield from _signals()

        r = affected_signals(self.h, OLD, DirtyRequest(frozenset({'s1'}), {'s1': 'n'}), gen())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(r.affected) + len(r.kept), 7)

    def test_level_mismatch_kept(self):
        sigs = [_sig('b1', 'sentence'), _sig('s1', 'block')]
        r = affected_signals(self.h, OLD, DirtyRequest(frozenset({'s1'}), {'s1': 'n'}), sigs)
        self.assertEqual(r.affected, ())
        self.assertEqual(len(r.kept), 2)


if __name__ == '__main__':
    unittest.main()

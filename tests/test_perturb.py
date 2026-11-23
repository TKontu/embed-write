import json
import unittest

from analysis.detectors import FOREIGN, MISSING, Detectors
from analysis.expected_moves import ExpectedMoves
from analysis.perturb import (DELETE, INSERT, SWAP, Perturbation,
                              delete_move, insert_move, log_record, perturb,
                              swap_moves)
from analysis.transitions import END, START, LabelledSection, TransitionStats


def sec(moves, kind='intro', doc='d'):
    return LabelledSection(doc, kind, tuple(moves))


class PrimitiveTests(unittest.TestCase):
    def test_delete(self):
        out, p = delete_move(sec('abc'), 1)
        self.assertEqual(out, sec('ac'))
        self.assertEqual(p, Perturbation('d', 'intro', DELETE, tuple('abc'),
                                         tuple('ac'), (1,), 'b'))

    def test_swap(self):
        out, p = swap_moves(sec('abc'), 2, 0)
        self.assertEqual(out.moves, tuple('cba'))
        self.assertEqual((p.kind, p.positions, p.move), (SWAP, (0, 2), None))

    def test_insert(self):
        out, p = insert_move(sec('abc'), 3, 'x')
        self.assertEqual(out.moves, tuple('abcx'))
        self.assertEqual((p.kind, p.positions, p.move), (INSERT, (3,), 'x'))
        self.assertEqual(p.original, tuple('abc'))

    def test_value_errors(self):
        s = sec('aab')
        for call in (lambda: delete_move(s, 3), lambda: delete_move(s, -1),
                     lambda: delete_move(sec(''), 0),
                     lambda: swap_moves(s, 0, 3), lambda: swap_moves(s, 0, 1),
                     lambda: swap_moves(s, 2, 2),
                     lambda: insert_move(s, 4, 'x'),
                     lambda: insert_move(s, 0, 'a'),
                     lambda: insert_move(s, 0, START),
                     lambda: insert_move(s, 0, END)):
            with self.assertRaises(ValueError):
                call()

    def test_type_errors(self):
        for call in (lambda: delete_move(('a',), 0),
                     lambda: swap_moves(None, 0, 1),
                     lambda: insert_move('ab', 0, 'x'),
                     lambda: list(perturb([('a',)], foreign_moves=['x'],
                                          seed=0))):
            with self.assertRaises(TypeError):
                call()


SECTIONS = [sec('abcd', doc=f'd{i}') for i in range(6)]


class PerturbTests(unittest.TestCase):
    def run_(self, sections=SECTIONS, seed=1, **kw):
        kw.setdefault('foreign_moves', ['x', 'y'])
        return list(perturb(iter(sections), seed=seed, **kw))

    def test_one_per_kind_and_ground_truth(self):
        out = self.run_()
        self.assertEqual(len(out), 18)
        self.assertEqual([p.kind for _, p in out[:3]], [DELETE, SWAP, INSERT])
        for s, p in out:
            self.assertEqual(s.moves, p.perturbed)
            if p.kind == DELETE:
                self.assertEqual(p.original[p.positions[0]], p.move)
            elif p.kind == SWAP:
                i, j = p.positions
                self.assertNotEqual(p.original[i], p.original[j])
                self.assertEqual(p.perturbed[i], p.original[j])
            else:
                self.assertIn(p.move, ('x', 'y'))
                self.assertEqual(p.perturbed[p.positions[0]], p.move)

    def test_determinism(self):
        self.assertEqual(self.run_(seed=7), self.run_(seed=7))
        runs = {tuple(self.run_(seed=s)) for s in range(10)}
        self.assertGreater(len(runs), 1)

    def test_skips_inapplicable(self):
        out = self.run_([sec(''), sec('aa'), sec('x')], foreign_moves=['x'])
        kinds = [(p.original, p.kind) for _, p in out]
        self.assertEqual(kinds, [((), INSERT), (tuple('aa'), DELETE),
                                 (tuple('aa'), INSERT), (('x',), DELETE)])

    def test_kinds_subset_and_empty(self):
        out = self.run_(kinds=(SWAP,))
        self.assertEqual({p.kind for _, p in out}, {SWAP})
        self.assertEqual(self.run_([]), [])
        with self.assertRaises(ValueError):
            self.run_(kinds=('bogus',))
        with self.assertRaises(ValueError):
            self.run_(foreign_moves=[START])

    def test_streams(self):
        def gen():
            yield SECTIONS[0]
            raise AssertionError('pulled too far')
        it = perturb(gen(), foreign_moves=['x'], seed=0)
        self.assertEqual(next(it)[1].kind, DELETE)

    def test_log_record_round_trip(self):
        _, p = insert_move(sec('ab'), 1, 'x')
        rec = log_record(p)
        self.assertEqual(json.loads(json.dumps(rec)), rec)
        self.assertEqual(rec['perturbed'], ['a', 'x', 'b'])
        self.assertEqual(rec['positions'], [1])


class EndToEndTests(unittest.TestCase):
    def test_detectors_flag_ground_truth(self):
        det = Detectors(TransitionStats.from_sections(SECTIONS),
                        ExpectedMoves.from_sections(SECTIONS))
        for s, p in perturb(SECTIONS, kinds=(DELETE, INSERT),
                            foreign_moves=['x'], seed=3):
            if p.kind == DELETE:
                found = {(f.kind, f.move) for f in det.missing(s)}
                self.assertIn((MISSING, p.move), found)
            else:
                found = {(f.kind, f.move, f.position) for f in det.foreign(s)}
                self.assertIn((FOREIGN, p.move, p.positions[0]), found)


if __name__ == '__main__':
    unittest.main()

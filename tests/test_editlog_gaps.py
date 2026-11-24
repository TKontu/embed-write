import builtins
import os
import tempfile
import unittest
from unittest import mock

from editlog import (EditLogStore, FeatureCount, GapReport, MoveCount,
                     SectionMoveCount, gap_report)
from editlog.schema import EditLogEntry
from analysis.signals import lint_display_name


def make(section, move, action, candidate='c', final='f'):
    return EditLogEntry(
        genre='g', section_type=section, move=move, original_text='o',
        candidate=candidate, final_text=final, action=action,
        panel_values={}, generation_run_id='run',
        timestamp='2026-11-24T10:00:00+00:00')


def words(text):
    return text.split()


class GapReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = EditLogStore(os.path.join(self.tmp.name, 'log.sqlite'))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fill(self):
        rows = [
            ('intro', 'gap', 'accept', 'a b', 'a b'),
            ('intro', 'gap', 'edit', 'a b x', 'a b y'),
            ('intro', 'claim', 'reject', 'q', 'q'),
            ('intro', 'claim', 'reject', 'q', 'q'),
            ('methods', 'gap', 'edit', 'x z', 'z w'),
            ('methods', 'claim', 'accept', 'q x', 'q x'),
            ('methods', 'aim', 'accept', 'x', 'x'),
            ('methods', 'aim', 'reject', 'x', 'x'),
        ]
        for s, m, a, c, f in rows:
            self.store.append(make(s, m, a, c, f))

    def test_empty_store_gives_empty_report(self):
        r = gap_report(self.store, features=words)
        self.assertEqual(r, GapReport(moves=(), section_moves=(), features=()))

    def test_per_move_counts_and_order(self):
        self.fill()
        r = gap_report(self.store)
        self.assertEqual(r.moves, (
            MoveCount('claim', total=3, accept=1, edit=0, reject=2, revised=2),
            MoveCount('gap', total=3, accept=1, edit=2, reject=0, revised=2),
            MoveCount('aim', total=2, accept=1, edit=0, reject=1, revised=1),
        ))

    def test_per_section_move_counts_and_order(self):
        self.fill()
        r = gap_report(self.store)
        self.assertEqual(r.section_moves, (
            SectionMoveCount('intro', 'claim', 2, 0, 0, 2, 2),
            SectionMoveCount('methods', 'aim', 2, 1, 0, 1, 1),
            SectionMoveCount('intro', 'gap', 2, 1, 1, 0, 1),
            SectionMoveCount('methods', 'gap', 1, 0, 1, 0, 1),
            SectionMoveCount('methods', 'claim', 1, 1, 0, 0, 0),
        ))

    def test_accepts_are_not_corrections(self):
        for _ in range(3):
            self.store.append(make('s', 'm', 'accept'))
        r = gap_report(self.store)
        self.assertEqual(r.moves, (MoveCount('m', 3, 3, 0, 0, 0),))

    def test_feature_counts_on_edit_entries_only(self):
        self.fill()
        r = gap_report(self.store, features=words)
        # edits: 'a b x'->'a b y' (rm x, add y); 'x z'->'z w' (rm x, add w)
        self.assertEqual(r.features, (
            FeatureCount('x', added=0, removed=2),
            FeatureCount('w', added=1, removed=0),
            FeatureCount('y', added=1, removed=0),
        ))

    def test_features_none_gives_empty_feature_section(self):
        self.fill()
        self.assertEqual(gap_report(self.store).features, ())

    def test_iterates_once_without_list(self):
        self.fill()
        calls = []
        orig = self.store.iter_entries

        def wrapped():
            calls.append(1)
            return orig()

        real_list = builtins.list

        def guard(*a):
            if a and getattr(a[0], 'gi_code', None) is not None and \
                    a[0].gi_code.co_name == 'iter_entries':
                raise AssertionError('store materialised with list()')
            return real_list(*a)

        with mock.patch.object(self.store, 'iter_entries', wrapped), \
                mock.patch.object(builtins, 'list', guard):
            gap_report(self.store, features=words)
        self.assertEqual(calls, [1])

    def test_report_is_frozen_and_names_neutral(self):
        r = gap_report(self.store)
        with self.assertRaises(Exception):
            r.moves = ()
        from editlog import gaps
        for label in gaps.DISPLAY_LABELS.values():
            lint_display_name(label)


if __name__ == '__main__':
    unittest.main()

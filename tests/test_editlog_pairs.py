import os
import tempfile
import types
import unittest

from editlog import (EditLogStore, NegativeRecord, TrainingPair,
                     iter_negatives, iter_training_pairs)
from editlog.schema import EditLogEntry


def make(i, action, **over):
    fields = dict(genre='g%d' % i, section_type='s%d' % i, move='m%d' % i,
                  original_text='o%d' % i, candidate='c%d' % i,
                  final_text='f%d' % i, action=action,
                  panel_values={'n': i}, generation_run_id='run-%d' % i,
                  timestamp='2026-11-24T10:00:00+00:00')
    fields.update(over)
    return EditLogEntry(**fields)


class PairsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = EditLogStore(os.path.join(self.tmp.name, 'log.sqlite'))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fill(self):
        actions = ['accept', 'reject', 'edit', 'reject', 'accept']
        return [(self.store.append(make(i, a)), make(i, a))
                for i, a in enumerate(actions)]

    def test_empty_store_yields_nothing(self):
        self.assertEqual(list(iter_training_pairs(self.store)), [])
        self.assertEqual(list(iter_negatives(self.store)), [])

    def test_generators_stream(self):
        self.assertIsInstance(iter_training_pairs(self.store), types.GeneratorType)
        self.assertIsInstance(iter_negatives(self.store), types.GeneratorType)

    def test_accept_and_edit_become_exact_pairs(self):
        rows = self.fill()
        expected = [TrainingPair(
            entry_id=eid, before=e.candidate, after=e.final_text,
            genre=e.genre, section_type=e.section_type, move=e.move,
            original_text=e.original_text, panel_values=e.panel_values,
            generation_run_id=e.generation_run_id, action=e.action)
            for eid, e in rows if e.action in ('accept', 'edit')]
        self.assertEqual(list(iter_training_pairs(self.store)), expected)

    def test_every_reject_is_a_negative_and_never_a_pair(self):
        rows = self.fill()
        rejects = [(eid, e) for eid, e in rows if e.action == 'reject']
        pair_ids = {p.entry_id for p in iter_training_pairs(self.store)}
        self.assertFalse(pair_ids & {eid for eid, _ in rejects})
        expected = [NegativeRecord(
            entry_id=eid, rejected=e.candidate, genre=e.genre,
            section_type=e.section_type, move=e.move,
            original_text=e.original_text, panel_values=e.panel_values,
            generation_run_id=e.generation_run_id) for eid, e in rejects]
        self.assertEqual(list(iter_negatives(self.store)), expected)

    def test_records_are_frozen(self):
        self.fill()
        pair = next(iter_training_pairs(self.store))
        with self.assertRaises(Exception):
            pair.before = 'x'


if __name__ == '__main__':
    unittest.main()

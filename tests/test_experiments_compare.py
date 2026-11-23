"""Offline EV-04 evidence using synthetic SQLite records."""
import importlib
import importlib.util
from itertools import permutations
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiments.store import ResultStore


def record(**changes):
    row = dict(gate='G-01', arm='a', metric='accuracy', value=0.75, n=20,
               interval=None, timestamp='2026-01-01', commit='synthetic',
               modelVersion='synthetic-v1', inventoryVersion='synthetic-v1')
    row.update(changes)
    return row


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'store.sqlite'
        self.store = ResultStore(self.path)
        self.addCleanup(self.store.close)

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.compare'),
                             'EV-04 comparison view is missing')
        return importlib.import_module('experiments.compare')

    def test_every_arm_including_loser_is_sorted_within_sorted_metrics(self):
        self.store.add_many([record(arm='z', value=0.1), record(arm='a'),
                             record(metric='agreement'), record(gate='G-02', arm='excluded')])
        result = self.module().compare_arms(self.store, 'G-01')
        self.assertEqual(list(result), ['accuracy', 'agreement'])
        self.assertEqual(result['accuracy'], [
            dict(arm='a', value=0.75, n=20, interval=None, superseded=0),
            dict(arm='z', value=0.1, n=20, interval=None, superseded=0)])

    def test_metric_filter(self):
        self.store.add_many([record(), record(metric='agreement')])
        self.assertEqual(list(self.module().compare_arms(
            self.store, 'G-01', metric='agreement')), ['agreement'])

    def test_latest_timestamp_not_insertion_order_and_superseded_count(self):
        self.store.add_many([record(timestamp='2026-03-01', value=0.9, n=30),
                             record(timestamp='2026-01-01'),
                             record(timestamp='2026-02-01')])
        row = self.module().compare_arms(self.store, 'G-01')['accuracy'][0]
        self.assertEqual(row, dict(arm='a', value=0.9, n=30, interval=None, superseded=2))
        self.assertIn('accuracy / a: 2 superseded rows',
                      self.module().render_comparison(self.store, 'G-01'))

    def test_footer_counts_hidden_rows_and_points_to_store(self):
        self.store.add_many([record(timestamp='2026-01-01', value=0.1),
                             record(timestamp='2026-02-01', value=-0.5),
                             record(timestamp='2026-03-01'),
                             record(arm='b', timestamp='2026-01-01', value=0.0),
                             record(arm='b', timestamp='2026-02-01')])
        output = self.module().render_comparison(self.store, 'G-01')
        self.assertIn('accuracy / a: 2 superseded rows', output)
        self.assertIn('accuracy / b: 1 superseded rows', output)
        self.assertTrue(output.endswith(
            '\n\n3 earlier rows not shown (counts per arm above); '
            'they remain in the store and in the full report.\n'), output)

    def test_timestamp_offsets_are_compared_chronologically(self):
        self.store.add_many([record(timestamp='2026-01-01T10:00:00+02:00'),
                             record(timestamp='2026-01-01T09:00:00Z', value=0.8)])
        self.assertEqual(self.module().compare_arms(self.store, 'G-01')
                         ['accuracy'][0]['value'], 0.8)

    def test_equal_timestamps_use_last_inserted_row(self):
        self.store.add_many([record(), record(value=0.8)])
        self.assertEqual(self.module().compare_arms(self.store, 'G-01')
                         ['accuracy'][0]['value'], 0.8)

    def test_negative_and_missing_intervals_render_unambiguously(self):
        self.store.add_many([record(value=-0.15, interval=(-0.2, -0.1)), record(arm='b')])
        self.assertEqual(self.module().render_comparison(self.store, 'G-01'),
                         '| metric | arm | value | n | interval |\n'
                         '| --- | --- | --- | --- | --- |\n'
                         '| accuracy | a | -0.15 | 20 | [-0.2, -0.1] |\n'
                         '| accuracy | b | 0.75 | 20 | — |\n')

    def test_empty_gate_or_metric_raises(self):
        module = self.module()
        self.store.add(record())
        for function in (module.compare_arms, module.render_comparison):
            with self.assertRaises(ValueError):
                function(self.store, 'G-02')
            with self.assertRaises(ValueError):
                function(self.store, 'G-01', metric='absent')

    def test_labels_cannot_break_markdown_table(self):
        self.store.add(record(arm='a|b\nc', metric='<metric>'))
        output = self.module().render_comparison(self.store, 'G-01')
        self.assertIn('&lt;metric&gt; | a&#124;b<br>c', output)
        self.assertEqual(len(output.splitlines()), 3)

    def test_cli_prints_table_and_honors_metric(self):
        module = self.module()
        self.store.add_many([record(), record(metric='agreement')])
        for extra in ([], ['--metric', 'agreement']):
            result = subprocess.run([sys.executable, '-m', 'experiments.compare',
                                     str(self.path), 'G-01', *extra],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, module.render_comparison(
                self.store, 'G-01', metric='agreement' if extra else None))

    def test_render_keeps_every_arm_regardless_of_value_order(self):
        for index, values in enumerate(permutations((0.1, 0.5, 0.9))):
            gate = f'G-{index}'
            with self.subTest(values=values):
                self.store.add_many(record(gate=gate, arm=arm, value=value)
                                    for arm, value in zip(('z', 'a', 'm'), values))
                report = self.module().render_comparison(self.store, gate)
                for arm, value in zip(('z', 'a', 'm'), values):
                    self.assertIn(f'| accuracy | {arm} | {value} |', report)

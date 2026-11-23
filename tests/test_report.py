"""Synthetic, offline evidence for EV-03."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiments.store import ResultStore
from scripts.lint_result import lint


def record(**changes):
    row = dict(gate='G-01', arm='a', metric='accuracy', value=0.75, n=20,
               interval=(0.5, 0.9), timestamp='2026-01-01', commit='abc123',
               modelVersion='model-v1', inventoryVersion='inventory-v1')
    row.update(changes)
    return row


class ReportTests(unittest.TestCase):
    def render(self, store, gate='G-01', **kwargs):
        self.assertIsNotNone(importlib.util.find_spec('experiments.report'),
                             'EV-03 report generator is missing')
        from experiments.report import render_report
        return render_report(store, gate, 'Synthetic question', **kwargs)

    def test_template_order_numbers_provenance_and_gate_filter(self):
        store = ResultStore(':memory:')
        self.addCleanup(store.close)
        store.add_many([record(), record(arm='b'),
                        record(metric='recall'), record(gate='G-02', metric='excluded')])
        report = self.render(store)
        template = Path('experiments/results/TEMPLATE.md').read_text()
        self.assertEqual([x for x in template.splitlines() if x.startswith('## ')],
                         [x for x in report.splitlines() if x.startswith('## ')])
        self.assertIn('accuracy: 0.75 (95% CI 0.5-0.9), n=20', report)
        self.assertNotIn('## Missing intervals', report)
        for text in ('commit: abc123', 'modelVersion: model-v1',
                     'inventoryVersion: inventory-v1', 'recall:'):
            self.assertIn(text, report)
        self.assertNotIn('excluded', report)
        self.assertLess(report.index('recall:'), report.index('### b'))
        self.assertEqual(report.count('### a'), 1)

    def test_missing_interval_refused_with_gate_arm_and_metric(self):
        store = ResultStore(':memory:')
        self.addCleanup(store.close)
        store.add_many([record(), record(arm='candidate', metric='recall', interval=None)])
        with self.assertRaises(ValueError) as error:
            self.render(store)
        for name in ('G-01', 'candidate', 'recall'):
            self.assertIn(name, str(error.exception))

    def test_draft_lists_every_missing_interval(self):
        store = ResultStore(':memory:')
        self.addCleanup(store.close)
        store.add_many([record(), record(arm='b', interval=None),
                        record(arm='c', metric='recall', interval=None),
                        record(gate='G-02', metric='excluded', interval=None)])
        report = self.render(store, allow_missing_interval=True)
        self.assertEqual(report.count('interval: NOT REPORTED (ST-02 violation)'), 2)
        self.assertIn('accuracy: 0.75 (95% CI 0.5-0.9), n=20', report)
        missing = report.split('## Missing intervals\n', 1)[1].split('## ', 1)[0]
        self.assertIn('gate: G-01; arm: b; metric: accuracy', missing)
        self.assertIn('gate: G-01; arm: c; metric: recall', missing)
        self.assertNotIn('excluded', report)
        self.assertNotIn('none recorded', report)

    def test_cli_requires_explicit_draft_override(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'store.sqlite'
            out = Path(directory) / 'report.md'
            store = ResultStore(db)
            store.add(record(interval=None))
            store.close()
            command = [sys.executable, '-m', 'experiments.report', '--store', str(db),
                       '--gate', 'G-01', '--out', str(out)]
            out.write_text('existing report')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(out.read_text(), 'existing report')
            result = subprocess.run(command + ['--allow-missing-interval'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('interval: NOT REPORTED (ST-02 violation)', out.read_text())
            self.assertIn('## Missing intervals', out.read_text())

    def test_empty_gate_raises(self):
        store = ResultStore(':memory:')
        self.addCleanup(store.close)
        with self.assertRaisesRegex(ValueError, 'G-01'):
            self.render(store)

    def test_verdict_remains_owner_placeholder_and_lint_explains_it(self):
        store = ResultStore(':memory:')
        self.addCleanup(store.close)
        store.add(record())
        report = self.render(store, hypothesis='Synthetic hypothesis',
                             threshold='Synthetic threshold', method='Synthetic method')
        verdict = report.split('## Verdict\n', 1)[1].split('## Fallback taken', 1)[0].strip()
        self.assertEqual(verdict, '<passed | failed | inconclusive — and who decided>')
        self.assertEqual(lint(report), ['placeholder left in section: Verdict',
                                        'placeholder left in section: Fallback taken'])
        filled = report.replace('<none, or the fallback from docs/architecture.md section 6 and its follow-up row>', 'None')
        self.assertEqual(lint(filled), ['placeholder left in section: Verdict'])
        self.assertEqual(lint(filled.replace(verdict, 'inconclusive — synthetic test owner')), [])

    def test_query_is_consumed_once_and_rows_rendered_before_advancing(self):
        class Stream:
            calls = 0
            def query(self, *, gate):
                self.calls += 1
                if self.calls != 1 or gate != 'G-01':
                    raise AssertionError('query must filter once')
                row = record()
                yield row
                row.clear()  # retaining raw rows until after iteration is invalid
                yield record(arm='b')
        store = Stream()
        report = self.render(store)
        self.assertEqual(store.calls, 1)
        self.assertEqual(report.count('accuracy:'), 2)

    def test_cli_writes_report_to_requested_path(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'store.sqlite'
            out = Path(directory) / 'report.md'
            store = ResultStore(db)
            store.add(record())
            store.close()
            result = subprocess.run([sys.executable, '-m', 'experiments.report',
                                     '--store', str(db), '--gate', 'G-01', '--out', str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('accuracy:', out.read_text())

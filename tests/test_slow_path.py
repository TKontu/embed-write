"""Offline orchestration checks with synthetic LLM-built signals."""
import importlib.util
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

from analysis.label_precedence import resolve_labels
from analysis.label_store import CandidateLabelStore
from analysis.signals import Signal

if importlib.util.find_spec('analysis.slow_path'):
    from analysis.slow_path import SlowPath
else:
    SlowPath = None


def signals(text, context):
    return [Signal('s', 'section', 'move', text, .8, 'synthetic',
                   'provisional', '2026-11-25T00:00:00Z')]


class SlowPathTests(unittest.TestCase):
    def make(self, review=signals, **kwargs):
        self.assertIsNotNone(SlowPath, 'SlowPath orchestration is missing')
        path = SlowPath(review, **kwargs)
        self.addCleanup(path.shutdown)
        return path

    def blocked(self, **kwargs):
        started, release = Event(), Event()
        def review(text, context):
            started.set()
            if not release.wait(3):
                raise TimeoutError('test did not release review')
            return signals(text, context)
        path = self.make(review, **kwargs)
        self.addCleanup(release.set)
        return path, started, release

    def test_submit_returns_before_review_finishes(self):
        path, started, release = self.blocked()
        with ThreadPoolExecutor(1) as caller:
            submitted = caller.submit(path.submit, 's', 'old', {})
            try:
                future = submitted.result(timeout=1)
                self.assertTrue(started.wait(1))
                self.assertFalse(future.done())
            finally:
                release.set()
        self.assertEqual(future.result(1), 'accepted')

    def test_result_is_reconciled_as_confirmed(self):
        path = self.make()
        self.assertEqual(path.submit('s', 'text', {}).result(1), 'accepted')
        self.assertEqual(path.current('s', 'section', 'move').layer, 'confirmed')

    def test_edit_discards_inflight_result(self):
        path, started, release = self.blocked()
        future = path.submit('s', 'old', {})
        self.assertTrue(started.wait(1))
        path.note_edit('s', 'new', {})
        release.set()
        self.assertEqual(future.result(1), 'stale')
        self.assertIsNone(path.current('s', 'section', 'move'))
        self.assertEqual(path.discard_count, 1)

    def test_cache_hit_skips_review(self):
        review = Mock(side_effect=signals)
        path = self.make(review)
        path.submit('s', 'text', {'b': 2, 'a': 1}).result(1)
        self.assertEqual(path.submit('s', 'text', {'a': 1, 'b': 2}).result(1), 'cached')
        self.assertEqual(review.call_count, 1)

    def test_context_change_misses_cache(self):
        review = Mock(side_effect=signals)
        path = self.make(review)
        path.submit('s', 'text', {'a': 1}).result(1)
        path.submit('s', 'text', {'a': 2}).result(1)
        self.assertEqual(review.call_count, 2)

    def test_context_change_discards_inflight_result(self):
        path, started, release = self.blocked()
        future = path.submit('s', 'text', {'a': 1})
        self.assertTrue(started.wait(1))
        path.note_edit('s', 'text', {'a': 2})
        release.set()
        self.assertEqual(future.result(1), 'stale')

    def test_exception_reported_and_worker_recovers(self):
        review = Mock(side_effect=[ValueError('review failed'), signals('ok', {})])
        path = self.make(review, max_workers=1)
        future = path.submit('s', 'text', {})
        with self.assertRaisesRegex(ValueError, 'review failed'):
            future.result(1)
        self.assertEqual(path.submit('s', 'ok', {}).result(1), 'accepted')

    def test_capacity_rejection_is_immediate_and_stales_old_work(self):
        path, started, release = self.blocked(max_workers=1, max_pending=1)
        old = path.submit('s', 'old', {})
        self.assertTrue(started.wait(1))
        self.assertEqual(path.submit('s', 'new', {}).result(1), 'busy')
        release.set()
        self.assertEqual(old.result(1), 'stale')

    def test_context_is_snapshotted(self):
        started, release = Event(), Event()
        def review(text, context):
            started.set()
            release.wait(3)
            return signals(str(context['nested']), {})
        path = self.make(review)
        self.addCleanup(release.set)
        context = {'nested': [1]}
        future = path.submit('s', 'text', context)
        self.assertTrue(started.wait(1))
        context['nested'].append(2)
        release.set()
        future.result(1)
        self.assertEqual(path.current('s', 'section', 'move').value, '[1]')

    def test_empty_result_is_cached(self):
        review = Mock(return_value=[])
        path = self.make(review)
        path.submit('s', 'text', {}).result(1)
        self.assertEqual(path.submit('s', 'text', {}).result(1), 'cached')
        self.assertEqual(review.call_count, 1)

    def test_invalid_signals_do_not_partially_publish(self):
        path = self.make(lambda text, context: signals(text, context) + [None])
        with self.assertRaises(TypeError):
            path.submit('s', 'text', {}).result(1)
        self.assertIsNone(path.current('s', 'section', 'move'))

    def test_confirmed_review_replaces_existing_provisional(self):
        from hashlib import sha256
        from analysis.reconcile_layers import LayerReconciler
        reconciler = LayerReconciler()
        reconciler.offer(signals('text', {})[0], sha256(b'text').hexdigest())
        path = self.make(reconciler=reconciler)
        path.submit('s', 'text', {}).result(1)
        self.assertEqual(path.current('s', 'section', 'move').layer, 'confirmed')

    def test_section_identity_prevents_cross_section_cache_hit(self):
        review = Mock(side_effect=signals)
        path = self.make(review)
        path.submit('s', 'text', {}).result(1)
        self.assertEqual(path.submit('other', 'text', {}).result(1), 'accepted')
        self.assertEqual(review.call_count, 2)

    def test_shutdown_rejects_submissions(self):
        path = self.make()
        path.shutdown()
        with self.assertRaises(RuntimeError):
            path.submit('s', 'text', {})


def two_signals(text, context):
    return [Signal('n1', 'section', 'move', text, .8, 'synthetic',
                   'provisional', '2026-11-25T00:00:00Z'),
            Signal('n2', 'section', 'move', 'ö', .7, 'synthetic',
                   'provisional', '2026-11-25T00:00:00Z')]


class SlowPathLabelStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(SlowPath, 'SlowPath orchestration is missing')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = os.path.join(tmp.name, 'labels.jsonl')
        self.store = CandidateLabelStore(self.file)

    def make(self, review=two_signals, **kwargs):
        kwargs.setdefault('label_store', self.store)
        kwargs.setdefault('model_version', 'synthetic-v1')
        kwargs.setdefault('clock', lambda: 1234.5)
        path = SlowPath(review, **kwargs)
        self.addCleanup(path.shutdown)
        return path

    def records(self):
        return list(self.store.iter_candidates())

    def test_accepted_review_stores_one_record_per_signal(self):
        path = self.make()
        self.assertEqual(path.submit('s', 'text', {}).result(1), 'accepted')
        self.assertEqual(self.records(), [
            {'node_id': 'n1', 'label': '["section","move","text"]', 'source': 'slow_layer',
             'model_version': 'synthetic-v1', 'timestamp': 1234.5},
            {'node_id': 'n2', 'label': '["section","move","ö"]', 'source': 'slow_layer',
             'model_version': 'synthetic-v1', 'timestamp': 1234.5},
        ])

    def test_stored_records_resolve(self):
        path = self.make()
        path.submit('s', 'text', {}).result(1)
        resolved = resolve_labels(self.records())
        self.assertEqual(sorted(resolved), ['n1', 'n2'])
        self.assertEqual(resolved['n1']['source'], 'slow_layer')

    def test_stale_result_stores_nothing(self):
        started, release = Event(), Event()
        def review(text, context):
            started.set()
            release.wait(3)
            return two_signals(text, context)
        path = self.make(review)
        self.addCleanup(release.set)
        future = path.submit('s', 'old', {})
        self.assertTrue(started.wait(1))
        path.note_edit('s', 'new', {})
        release.set()
        self.assertEqual(future.result(1), 'stale')
        self.assertFalse(os.path.exists(self.file))

    def test_cached_resubmission_stores_nothing_new(self):
        path = self.make()
        path.submit('s', 'text', {}).result(1)
        self.assertEqual(path.submit('s', 'text', {}).result(1), 'cached')
        self.assertEqual(len(self.records()), 2)

    def test_append_failure_surfaces_and_releases_capacity(self):
        store = Mock()
        store.append.side_effect = OSError('disk full')
        path = self.make(label_store=store, max_pending=1)
        future = path.submit('s', 'text', {})
        self.assertIsInstance(future.exception(1), OSError)
        store.append.side_effect = None
        self.assertEqual(path.submit('s', 'other', {}).result(1), 'accepted')

    def test_store_requires_model_version(self):
        for bad in (None, '', 3):
            with self.assertRaises(ValueError):
                SlowPath(two_signals, label_store=self.store, model_version=bad)

    def test_no_store_writes_no_file(self):
        path = SlowPath(two_signals)
        self.addCleanup(path.shutdown)
        self.assertEqual(path.submit('s', 'text', {}).result(1), 'accepted')
        self.assertFalse(os.path.exists(self.file))

"""Offline orchestration checks with synthetic LLM-built signals."""
import importlib.util
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

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

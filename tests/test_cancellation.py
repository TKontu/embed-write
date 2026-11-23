"""SV-04 interleaved edits over real loopback HTTP, without timing sleeps."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from service.client import AnalysisClient
from service.contract import node_hash
from service.server import AnalysisService


class CancellationTest(unittest.TestCase):
    def setUp(self):
        self.started = threading.Event()
        self.release = threading.Event()

        def handler(items):
            if any(item['text'] == 'old' for item in items):
                self.started.set()
                if not self.release.wait(5):
                    raise RuntimeError('test handler release timed out')
            return [item['text'].upper() for item in items]

        self.service = AnalysisService(handler).start()
        host, port = self.service.address
        self.client = AnalysisClient(f'http://{host}:{port}', timeout=5)
        self.addCleanup(self.service.stop)
        self.addCleanup(lambda: getattr(self.client, 'close', lambda: None)())
        self.addCleanup(self.release.set)

    def test_sync_edit_drops_stale_node_but_preserves_other_results(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            old = executor.submit(self.client.analyze, {'a': 'old', 'b': 'stable'}, {})
            try:
                self.assertTrue(self.started.wait(3))
                self.assertEqual(self.client.analyze({'a': 'new'}, {}), {'a': 'NEW'})
            finally:
                self.release.set()
            self.assertEqual(old.result(3), {'b': 'STABLE'})

    def test_new_submit_supersedes_even_identical_text(self):
        self.assertTrue(callable(getattr(self.client, 'submit', None)))
        old = self.client.submit({'a': 'old'}, {})
        self.assertTrue(self.started.wait(3))
        new = self.client.submit({'a': 'old'}, {})
        self.release.set()
        self.assertEqual(old.result(3), {})
        self.assertEqual(new.result(3), {'a': 'OLD'})

    def test_clean_edit_invalidates_pending_result_without_http(self):
        self.assertTrue(callable(getattr(self.client, 'submit', None)))
        old = self.client.submit({'a': 'old', 'b': 'stable'}, {})
        self.assertTrue(self.started.wait(3))
        self.assertEqual(self.client.analyze({'a': 'cached'}, {'a': node_hash('cached')}), {})
        self.release.set()
        self.assertEqual(old.result(3), {'b': 'STABLE'})

    def test_unchanged_results_and_close_joins_workers(self):
        self.assertTrue(callable(getattr(self.client, 'submit', None)))
        before = set(threading.enumerate())
        self.assertEqual(self.client.submit({'a': 'stable'}, {}).result(3), {'a': 'STABLE'})
        workers = set(threading.enumerate()) - before
        self.client.close()
        self.assertFalse(any(t.is_alive() for t in workers if t.name.startswith('analysis-client')))
        with self.assertRaises(RuntimeError):
            self.client.submit({'a': 'closed'}, {})

    def test_queued_superseded_request_is_cancelled(self):
        # Occupy both workers before queuing the node that will be superseded.
        second_started = threading.Event()
        original = self.service._handler

        def handler(items):
            if items[0]['id'] == 'block2':
                second_started.set()
            return original(items)

        self.service._handler = handler
        first = self.client.submit({'block1': 'old'}, {})
        second = self.client.submit({'block2': 'old'}, {})
        self.assertTrue(self.started.wait(3))
        self.assertTrue(second_started.wait(3))
        queued = self.client.submit({'a': 'obsolete'}, {})
        latest = self.client.submit({'a': 'fresh'}, {})
        self.assertTrue(queued.cancelled())
        self.release.set()
        self.assertEqual(latest.result(3), {'a': 'FRESH'})
        first.result(3)
        second.result(3)
        self.assertEqual(self.client._latest, {})
        self.assertEqual(self.client._pending, {})

    def test_submit_snapshots_input_and_does_not_retain_finished_nodes(self):
        current = {'a': 'old'}
        future = self.client.submit(current, {})
        self.assertTrue(self.started.wait(3))
        current['a'] = 'mutated without notification'
        self.release.set()
        self.assertEqual(future.result(3), {'a': 'OLD'})
        self.assertEqual(self.client._latest, {})
        self.assertEqual(self.client._pending, {})

    def test_http_failure_cleans_tracking(self):
        from service.contract import ContractError

        with self.assertRaises(ContractError):
            self.client.submit({'a': 'x' * 20001}, {}).result(3)
        self.assertEqual(self.client._latest, {})
        self.assertEqual(self.client._pending, {})

    def test_close_discards_running_results_and_joins(self):
        future = self.client.submit({'a': 'old'}, {})
        self.assertTrue(self.started.wait(3))
        # Observe shutdown starting before allowing the HTTP exchange to finish.
        shutdown_started = threading.Event()
        shutdown = self.client._executor.shutdown

        def observed_shutdown(*args, **kwargs):
            shutdown_started.set()
            return shutdown(*args, **kwargs)

        self.client._executor.shutdown = observed_shutdown
        closer = threading.Thread(target=self.client.close)
        closer.start()
        try:
            self.assertTrue(shutdown_started.wait(3))
        finally:
            self.release.set()
            closer.join(3)
        self.assertFalse(closer.is_alive())
        self.assertEqual(future.result(3), {})
        self.assertEqual(self.client._pending, {})

"""Offline triage acceptance checks; fake reviews only."""
import importlib.util
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

from analysis.slow_path import SlowPath

if importlib.util.find_spec('analysis.triage'):
    from analysis.triage import Sentence, TriageSession
else:
    Sentence = TriageSession = None


class TriageTests(unittest.TestCase):
    def make(self, review=None, **kwargs):
        self.assertIsNotNone(TriageSession, 'session triage is missing')
        path = SlowPath(review or Mock(return_value=[]), **kwargs)
        self.addCleanup(path.shutdown)
        return path, TriageSession(path, session_id='session-a', cutoff=.7)

    def test_only_below_cutoff_sent_with_section_context(self):
        review = Mock(return_value=[])
        path, session = self.make(review)
        futures = session.submit_section('section', 'whole section', [
            Sentence('low', 'uncertain', .69), Sentence('edge', 'equal', .7),
            Sentence('high', 'confident', 1)], edited_section_id='other',
            context={'genre': 'report'})
        self.assertEqual(list(futures), ['low'])
        self.assertEqual(futures['low'].result(1), 'accepted')
        review.assert_called_once_with('uncertain', {'genre': 'report'})
        self.assertEqual(session.call_count, 1)

    def test_edited_section_always_submitted_once(self):
        review = Mock(return_value=[])
        path, session = self.make(review)
        futures = session.submit_section('section', 'whole', [
            Sentence('high', 'confident', .9)], edited_section_id='section', context={})
        self.assertEqual(list(futures), ['section'])
        futures['section'].result(1)
        review.assert_called_once_with('whole', {})

    def test_edited_section_and_uncertain_sentence_have_separate_identity(self):
        path, session = self.make()
        futures = session.submit_section('section', 'whole', [Sentence('low', 'part', .1)],
                                         edited_section_id='section', context={})
        self.assertEqual(set(futures), {'section', 'low'})
        self.assertEqual([f.result(1) for f in futures.values()], ['accepted', 'accepted'])

    def test_counts_and_logs_are_per_session_including_cache_hits(self):
        path, session = self.make()
        other = TriageSession(path, session_id='session-b', cutoff=.7)
        with self.assertLogs('analysis.triage', level='INFO') as logs:
            for _ in range(2):
                session.submit_section('s', 'whole', [], edited_section_id='s', context={})['s'].result(1)
        self.assertEqual(session.call_count, 2)
        self.assertEqual(other.call_count, 0)
        self.assertEqual(session.busy_count, 0)
        self.assertIn('session-a', logs.output[-1])
        self.assertIn('calls=2', logs.output[-1])
        self.assertNotIn('whole', '\n'.join(logs.output))

    def test_full_path_returns_without_waiting_and_counts_busy(self):
        entered, release = Event(), Event()
        def review(text, context):
            entered.set()
            if not release.wait(3):
                raise TimeoutError('review not released')
            return []
        path, session = self.make(review, max_workers=1, max_pending=1)
        self.addCleanup(release.set)
        first = session.submit_section('a', 'first', [], edited_section_id='a', context={})['a']
        self.assertTrue(entered.wait(1))
        with ThreadPoolExecutor(1) as caller:
            try:
                with self.assertLogs('analysis.triage', level='INFO') as logs:
                    result = caller.submit(session.submit_section, 'b', 'second', [],
                                           edited_section_id='b', context={}).result(1)
                self.assertEqual(result['b'].result(1), 'busy')
                self.assertFalse(first.done())
                self.assertEqual(session.call_count, 2)
                self.assertEqual(session.busy_count, 1)
                self.assertIn('busy=1', logs.output[-1])
            finally:
                release.set()
        first.result(1)

    def test_invalid_cutoffs_raise(self):
        path, session = self.make()
        for cutoff in [-.01, 1.01, float('nan'), float('inf'), -float('inf')]:
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                TriageSession(path, session_id='invalid', cutoff=cutoff)

    def test_cutoff_endpoints(self):
        path, session = self.make()
        for cutoff, expected in [(0, []), (1, ['zero'])]:
            session = TriageSession(path, session_id='boundary', cutoff=cutoff)
            futures = session.submit_section('s', 'whole', [Sentence('zero', 'zero', 0),
                Sentence('one', 'one', 1)], edited_section_id=None, context={})
            self.assertEqual(list(futures), expected)
            for future in futures.values():
                future.result(1)

    def test_review_errors_remain_on_future(self):
        path, session = self.make(Mock(side_effect=ValueError('fake failure')))
        future = session.submit_section('s', 'whole', [], edited_section_id='s', context={})['s']
        with self.assertRaisesRegex(ValueError, 'fake failure'):
            future.result(1)
        self.assertEqual(session.call_count, 1)
        self.assertEqual(session.busy_count, 0)

    def test_invalid_sentence_data_rejected_before_submission(self):
        path, session = self.make()
        for sentences in [[Sentence('s', 'collision', .1)],
                          [Sentence('x', 'one', .1), Sentence('x', 'two', .2)],
                          [Sentence('x', 'invalid', float('nan'))]]:
            with self.subTest(sentences=sentences), self.assertRaises(ValueError):
                session.submit_section('s', 'whole', sentences, edited_section_id='s', context={})
        self.assertEqual(session.call_count, 0)

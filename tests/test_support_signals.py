"""Synthetic offline checks for SP-05."""

from dataclasses import FrozenInstanceError, asdict
import unittest

from analysis.signal_gates import SignalFlag, default_flags
from analysis.signals import Signal
from analysis.support_signals import (
    SupportLink, SupportMap, emit_support_signals, unsupported_claims, unused_evidence,
)

STAMP = '2026-11-23T00:00:00Z'
ON = {'support': SignalFlag('support', ('G-07',), True)}


class SupportSignalsTests(unittest.TestCase):
    def setUp(self):
        self.mapping = SupportMap('sentence', ('c3', 'c1', 'c2'),
                                  ('e3', 'e1', 'e2'), (
            SupportLink('c1', 'e1', 0.2),
            SupportLink('c2', 'e2', 0.5),
            SupportLink('c1', 'e1', 0.3),
        ))

    def test_default_and_missing_flags_emit_nothing(self):
        for flags in (default_flags(), {}):
            self.assertEqual(emit_support_signals(
                self.mapping, flags=flags, computed_at=STAMP), [])

    def test_enabled_emits_both_statuses_in_input_order(self):
        actual = emit_support_signals(self.mapping, flags=ON, computed_at=STAMP)
        self.assertEqual([s.node_id for s in actual], ['c3', 'c1', 'e3', 'e1'])
        self.assertEqual([s.value['status'] for s in actual],
                         ['unsupported', 'unsupported', 'evidence_unused', 'evidence_unused'])
        self.assertEqual(actual, unsupported_claims(self.mapping, computed_at=STAMP)
                         + unused_evidence(self.mapping, computed_at=STAMP))
        for signal in actual:
            self.assertEqual(Signal(**asdict(signal)), signal)
            self.assertEqual(signal.kind, 'support')
            self.assertEqual(signal.layer, 'provisional')
            self.assertEqual(signal.level, 'sentence')
            self.assertEqual(signal.computed_at, STAMP)
        self.assertEqual(actual[1].value['best_score'], 0.3)
        self.assertAlmostEqual(actual[1].confidence, 0.7)
        self.assertEqual(actual[3].value['best_score'], 0.3)
        self.assertEqual(actual[1].method_ref,
                         'support_signals.unsupported_claims@threshold=0.5')
        self.assertEqual(actual[3].method_ref,
                         'support_signals.unused_evidence@threshold=0.5')

    def test_no_links_have_full_confidence(self):
        for signal in emit_support_signals(self.mapping, flags=ON, computed_at=STAMP)[::2]:
            self.assertEqual(signal.confidence, 1.0)
            self.assertIsNone(signal.value['best_score'])

    def test_boundary_and_unit_threshold_are_inclusive(self):
        for score in (0.5, 1):
            mapping = SupportMap('sentence', ('c',), ('e',), (SupportLink('c', 'e', score),))
            self.assertEqual(emit_support_signals(
                mapping, threshold=score, flags=ON, computed_at=STAMP), [])

    def test_best_link_across_multiple_nodes_and_link_order(self):
        links = (SupportLink('c1', 'e1', 0), SupportLink('c1', 'e2', 0.8),
                 SupportLink('c2', 'e1', 0.9))
        for ordered in (links, tuple(reversed(links))):
            mapping = SupportMap('sentence', ('c1', 'c2'), ('e1', 'e2'), ordered)
            self.assertEqual(emit_support_signals(mapping, flags=ON, computed_at=STAMP), [])

    def test_zero_is_distinct_from_no_link(self):
        mapping = SupportMap('sentence', ('c',), ('e',), (SupportLink('c', 'e', 0),))
        for signal in emit_support_signals(mapping, flags=ON, computed_at=STAMP):
            self.assertEqual(signal.value['best_score'], 0.0)
            self.assertIsInstance(signal.value['best_score'], float)
            self.assertEqual(signal.confidence, 1.0)

    def test_empty_map(self):
        self.assertEqual(emit_support_signals(
            SupportMap('sentence', (), (), ()), flags=ON, computed_at=STAMP), [])

    def test_unknown_link_ids_rejected(self):
        for claim, evidence in (('unknown', 'e'), ('c', 'unknown')):
            with self.subTest(claim=claim, evidence=evidence), self.assertRaises(ValueError):
                SupportMap('sentence', ('c',), ('e',), (SupportLink(claim, evidence, 0.5),))

    def test_duplicate_ids_rejected(self):
        for claims, evidence in ((('c', 'c'), ('e',)), (('c',), ('e', 'e'))):
            with self.assertRaises(ValueError):
                SupportMap('sentence', claims, evidence, ())

    def test_bad_scores_rejected(self):
        for score in (-0.1, 1.1, float('nan'), float('inf'), -float('inf'),
                      None, '0.5', True, 10 ** 400):
            with self.subTest(score=score), self.assertRaises(ValueError):
                SupportLink('c', 'e', score)

    def test_bad_thresholds_rejected_by_every_entry_point(self):
        for threshold in (0, -1, 1.1, float('nan'), float('inf'), None, '0.5', True):
            for function, kwargs in ((unsupported_claims, {}), (unused_evidence, {}),
                                     (emit_support_signals, {'flags': ON}),
                                     (emit_support_signals, {'flags': {}})):
                with self.subTest(threshold=threshold, function=function), self.assertRaises(ValueError):
                    function(self.mapping, threshold=threshold, computed_at=STAMP, **kwargs)

    def test_timestamp_is_required_and_nonempty(self):
        for function, kwargs in ((unsupported_claims, {}), (unused_evidence, {}),
                                 (emit_support_signals, {'flags': ON})):
            with self.assertRaises(TypeError):
                function(self.mapping, **kwargs)
            for stamp in ('', '  ', None, 42):
                with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                    function(self.mapping, computed_at=stamp, **kwargs)

    def test_dataclasses_are_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.mapping.level = 'document'
        with self.assertRaises(FrozenInstanceError):
            self.mapping.links[0].score = 0.9


if __name__ == '__main__':
    unittest.main()

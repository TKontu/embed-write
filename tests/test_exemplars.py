"""Offline, synthetic GE-02 acceptance checks."""

import importlib
import importlib.util
import json
import unittest

from generation.context import GenerationContext, Passage
from generation.run_record import GenerationRunRecord, SamplingParams


class ExemplarTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('generation.exemplars'),
                             'GE-02 exemplar selection is missing')
        self.api = importlib.import_module('generation.exemplars')
        self.context = GenerationContext(Passage('selected', 'Selected text.', 'claim'),
                                         's1', 'Results', 'Section text.')

    def candidate(self, id='other:p1', document_id='other', section_type='results',
                  move='claim', text='Example café.'):
        return self.api.Exemplar(id, document_id, section_type, move, text)

    def select(self, candidates, limit=2):
        return self.api.select_exemplars(candidates, current_document_id='current',
                                         section_type='results', move='claim', limit=limit)

    def render(self, candidates, limit=2):
        return self.api.render_prompt(self.context, candidates,
                                       current_document_id='current',
                                       section_type='results', limit=limit)

    def test_exact_section_and_move_only(self):
        good = self.candidate()
        self.assertEqual(self.select([self.candidate(section_type='Results'),
                                      self.candidate(move='Claim'), good]), (good,))

    def test_current_document_excluded_even_as_only_match(self):
        own = self.candidate(document_id='current')
        self.assertEqual(self.select([own]), ())
        good = self.candidate(id='external')
        self.assertEqual(self.select([own, good, own]), (good,))

    def test_limit_stops_stream_without_overread(self):
        first, second = self.candidate(id='z'), self.candidate(id='a')
        def stream():
            yield self.candidate(move='other')
            yield first
            yield self.candidate(document_id='current')
            yield second
            raise AssertionError('stream over-read')
        self.assertEqual(self.select(stream()), (first, second))

    def test_zero_limit_does_not_touch_iterable(self):
        class Untouchable:
            def __iter__(self):
                raise AssertionError('iterable touched')
        self.assertEqual(self.select(Untouchable(), 0), ())

    def test_invalid_limits_raise_value_error(self):
        for limit in (-1, True, False, 1.5, '2', None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.select([], limit)

    def test_prompt_preserves_context_text_order_and_record_ids(self):
        candidates = [self.candidate(id='z'), self.candidate(id='a', text='Second example.')]
        prompt, ids = self.render(iter(candidates))
        repeated, repeated_ids = self.render(iter(candidates))
        self.assertEqual(prompt.encode('utf-8'), repeated.encode('utf-8'))
        self.assertEqual(ids, repeated_ids)
        prefix = self.context.render_prompt() + '\nExemplars:\n'
        self.assertTrue(prompt.startswith(prefix))
        payload = json.loads(prompt[len(prefix):])
        self.assertEqual([e['text'] for e in payload], [e.text for e in candidates])
        for candidate in candidates:
            self.assertIn(candidate.text, prompt)
        self.assertEqual(ids, ('z', 'a'))
        record = GenerationRunRecord.build(prompt, ids, 'synthetic',
                                            [SamplingParams(1, 0.2, 1.0, 10)], ['rewrite'])
        self.assertEqual(record.exemplar_ids, ids)

    def test_no_matches_render_empty_list(self):
        for candidates in ([], [self.candidate(document_id='current')],
                           [self.candidate(move='other')]):
            with self.subTest(candidates=candidates):
                prompt, ids = self.render(candidates)
                self.assertEqual(prompt, self.context.render_prompt() + '\nExemplars:\n[]')
                self.assertEqual(ids, ())

    def test_serialization_round_trips_special_text(self):
        text = 'Quote " and newline\nwith \\ and café'
        prompt, _ = self.render([self.candidate(text=text)])
        payload = prompt[len(self.context.render_prompt() + '\nExemplars:\n'):]
        self.assertEqual(json.loads(payload)[0]['text'], text)

    def test_candidate_ids_are_nonempty_strings(self):
        for id in ('', 12, None):
            with self.subTest(id=id), self.assertRaises(ValueError):
                self.candidate(id=id)


if __name__ == '__main__':
    unittest.main()

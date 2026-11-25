"""Offline, synthetic acceptance checks for the GE-03 proposal flow (R63/A2).

No model, network or corpus: a fake client records calls and a deterministic
fake embedder maps text to fixed vectors.
"""

import importlib
import importlib.util
import unittest
from dataclasses import FrozenInstanceError

from generation.candidates import vary_sampling
from generation.context import GenerationContext, Passage
from generation.exemplars import Exemplar, render_prompt
from generation.llm_client import LLMClient
from generation.run_record import SamplingParams, replay
from service.verify_panel import build_panel
from service.vectors import Level, LevelVector


def vector(*values):
    return LevelVector(Level.BLOCK, values)


def basis_vectors(count, dimensions=None):
    dimensions = dimensions or count
    return [vector(*[1 if d == i else 0 for d in range(dimensions)])
            for i in range(count)]


class FakeClient:
    """Records every completion; replies deterministically from the seed."""

    def __init__(self, model='fake-model', replies=None, fail_at=None):
        self.model = model
        self.calls = []
        self._replies = dict(replies or {})
        self._fail_at = fail_at

    def complete(self, prompt, sampling):
        if self._fail_at is not None and len(self.calls) == self._fail_at:
            raise RuntimeError('fake endpoint failed')
        self.calls.append((prompt, sampling))
        return self._replies.get(sampling.seed, f'text-{sampling.seed}')


class FakeEmbed:
    """Records its single input and returns the mapped vectors in order."""

    def __init__(self, vectors):
        self.calls = []
        self._vectors = dict(vectors)

    def __call__(self, texts):
        self.calls.append(tuple(texts))
        return [self._vectors[text] for text in texts]


class ProposeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('generation.propose'),
                             'GE-03 proposal flow is missing')
        self.api = importlib.import_module('generation.propose')
        self.context = GenerationContext(
            Passage('selected', 'Original passage text.', 'claim'),
            's1', 'Results', 'Section body text.')
        self.exemplars = (
            Exemplar('own-1', 'current', 'results', 'claim', 'Own document example.'),
            Exemplar('ext-1', 'other', 'results', 'claim', 'External example one.'),
            Exemplar('ext-2', 'other', 'results', 'claim', 'External example two.'),
        )
        self.base = SamplingParams(10, 0.5, 0.9, 64)

    def propose(self, client, embed, *, n=4, cutoff=0.9, exemplars=None):
        return self.api.propose(
            self.context,
            self.exemplars if exemplars is None else exemplars,
            client=client, base_sampling=self.base, n=n, embed=embed,
            cutoff=cutoff, current_document_id='current',
            section_type='results', exemplar_limit=2)

    def orthogonal_embed(self, texts):
        texts = list(texts)
        return FakeEmbed(dict(zip(texts, basis_vectors(len(texts)))))

    def test_one_ordered_completion_per_varied_sampling(self):
        client, embed = FakeClient(), self.orthogonal_embed([f'text-{s}' for s in range(10, 14)])
        self.propose(client, embed)
        expected_prompt = render_prompt(
            self.context, self.exemplars, current_document_id='current',
            section_type='results', limit=2)[0]
        self.assertEqual(len(client.calls), 4)
        for (prompt, sampling), expected in zip(client.calls,
                                                vary_sampling(self.base, 4)):
            self.assertEqual(prompt, expected_prompt)
            self.assertEqual(sampling, expected)
        self.assertEqual([s.seed for _, s in client.calls], [10, 11, 12, 13])

    def test_record_holds_every_input_and_all_raw_candidates(self):
        client = FakeClient()
        embed = self.orthogonal_embed([f'text-{s}' for s in range(10, 14)])
        result = self.propose(client, embed)
        record = result.record
        self.assertEqual(record.prompt, client.calls[0][0])
        self.assertEqual(record.exemplar_ids, ('ext-1', 'ext-2'))
        self.assertEqual(record.model, 'fake-model')
        self.assertEqual(record.sampling, tuple(vary_sampling(self.base, 4)))
        self.assertEqual(record.candidates,
                         tuple(f'text-{s}' for s in range(10, 14)))
        self.assertTrue(replay(record, lambda p, e, m, s: client.complete(p, s)))

    def test_near_duplicates_and_exact_repeats_are_dropped_in_order(self):
        replies = {10: 'alpha', 11: 'near-alpha', 12: 'beta', 13: 'alpha'}
        client = FakeClient(replies=replies)
        embed = FakeEmbed({'alpha': vector(1, 0), 'near-alpha': vector(1, 0.01),
                           'beta': vector(0, 1)})
        result = self.propose(client, embed, cutoff=0.99)
        self.assertEqual(result.candidates, ('alpha', 'beta'))
        self.assertEqual(result.dropped_count, 2)
        self.assertEqual(len(result.record.candidates), 4)
        self.assertEqual(embed.calls, [('alpha', 'near-alpha', 'beta', 'alpha')])

    def test_one_panel_per_kept_candidate_against_the_context_passage(self):
        client = FakeClient()
        texts = [f'text-{s}' for s in range(10, 14)]
        embed = FakeEmbed(dict(zip(texts, basis_vectors(len(texts)))))
        result = self.propose(client, embed)
        self.assertEqual(len(result.panels), len(result.candidates))
        self.assertEqual(result.dropped_count, 0)
        for panel, candidate in zip(result.panels, result.candidates):
            self.assertEqual(panel.to_dict(),
                             build_panel(self.context.passage.text, candidate).to_dict())

    def test_current_document_exemplar_never_reaches_the_prompt(self):
        client, embed = FakeClient(), self.orthogonal_embed([f'text-{s}' for s in range(10, 14)])
        result = self.propose(client, embed)
        prompt = client.calls[0][0]
        self.assertNotIn('Own document example.', prompt)
        self.assertNotIn('own-1', prompt)
        self.assertEqual(result.record.exemplar_ids, ('ext-1', 'ext-2'))
        self.assertEqual(prompt, render_prompt(
            self.context, self.exemplars, current_document_id='current',
            section_type='results', limit=2)[0])

    def test_invalid_n_raises_before_any_call(self):
        client, embed = FakeClient(), FakeEmbed({})
        with self.assertRaises(ValueError):
            self.propose(client, embed, n=0)
        self.assertEqual(client.calls, [])
        self.assertEqual(embed.calls, [])

    def test_client_error_propagates_without_a_result(self):
        client = FakeClient(fail_at=2)
        embed = self.orthogonal_embed([f'text-{s}' for s in range(10, 14)])
        with self.assertRaises(RuntimeError):
            self.propose(client, embed)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(embed.calls, [])

    def test_embed_wrong_count_raises_after_one_call_with_all_raw_texts(self):
        client = FakeClient()
        raw = [f'text-{s}' for s in range(10, 14)]

        class ShortEmbed:
            def __init__(self):
                self.calls = []

            def __call__(self, texts):
                self.calls.append(tuple(texts))
                return [vector(1, 0)] * (len(texts) - 1)

        embed = ShortEmbed()
        with self.assertRaises(ValueError):
            self.propose(client, embed)
        self.assertEqual(embed.calls, [tuple(raw)])

    def test_result_is_frozen_and_inputs_are_untouched(self):
        client, embed = FakeClient(), self.orthogonal_embed([f'text-{s}' for s in range(10, 14)])
        result = self.propose(client, embed)
        with self.assertRaises(FrozenInstanceError):
            result.candidates = ()
        self.assertEqual(self.context.passage.text, 'Original passage text.')
        self.assertEqual(self.exemplars[1].text, 'External example one.')

    def test_llm_client_exposes_a_read_only_model(self):
        client = LLMClient('http://localhost/v1', 'local-model')
        self.assertEqual(client.model, 'local-model')
        with self.assertRaises(AttributeError):
            client.model = 'other'


if __name__ == '__main__':
    unittest.main()

"""Synthetic LLM-built checks for the unwired G-03 contextual-prefix arm."""
import unittest

from experiments.arms.contextual_prefix import CONTEXTUAL_PREFIX, contextual_embed
from service.chunk import Chunk
from service.embedder import EmbedderError, HashEmbedder
from service.vectors import Level

from experiments.arms.contextual_prefix import ContextualPrefixError, build_prefixed_text


class PrefixTests(unittest.TestCase):
    def test_exact_context_path(self):
        self.assertEqual(build_prefixed_text('Sentence.', [' Title ', 'Section']),
                         'Title > Section\n\nSentence.')

    def test_blank_parts_are_skipped(self):
        self.assertEqual(build_prefixed_text('body', ['', ' A ', ' \t', 'B']),
                         'A > B\n\nbody')

    def test_empty_context_preserves_text(self):
        for context in ([], ['', ' \t']):
            with self.subTest(context=context):
                self.assertEqual(build_prefixed_text(' body\n', context), ' body\n')

    def test_truncation_preserves_unicode_and_full_text(self):
        self.assertEqual(build_prefixed_text('body\n尾', ['é😀abc'], max_prefix_chars=2),
                         'é😀\n\nbody\n尾')

    def test_custom_separator(self):
        self.assertEqual(build_prefixed_text('x', ['a', 'b'], separator='/'), 'a/b\n\nx')

    def test_invalid_context_parts(self):
        for part in (None, 12, b'title', 'a\nb', 'a\rb', '\n'):
            with self.subTest(part=part), self.assertRaises(ContextualPrefixError):
                build_prefixed_text('x', [part])

    def test_nonpositive_prefix_limit(self):
        for limit in (0, -1):
            with self.subTest(limit=limit), self.assertRaises(ContextualPrefixError):
                build_prefixed_text('x', [], max_prefix_chars=limit)

    def test_empty_separator(self):
        with self.assertRaises(ContextualPrefixError):
            build_prefixed_text('x', [], separator='')


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [Chunk(str(i), Level.SENTENCE, 'block', f'Text {i}')
                       for i in range(5)]

    def test_bounded_lazy_batches_preserve_order_and_levels(self):
        events = []
        backend = HashEmbedder(dims=4)

        class RecordingEmbedder:
            dims = backend.dims

            def embed(self, texts, level):
                events.append(('embed', len(texts)))
                return backend.embed(texts, level)

        def context_for(chunk):
            events.append(('context', chunk.node_id))
            return [' Title ', chunk.node_id]

        actual = contextual_embed(self.chunks, context_for, RecordingEmbedder(),
                                  Level.SENTENCE, batch_size=2, separator='/',
                                  max_prefix_chars=7)
        expected = backend.embed([f'Title/{i}\n\nText {i}' for i in range(5)],
                                 Level.SENTENCE)
        self.assertEqual(actual, expected)
        self.assertEqual(events, [('context', '0'), ('context', '1'), ('embed', 2),
                                  ('context', '2'), ('context', '3'), ('embed', 2),
                                  ('context', '4'), ('embed', 1)])
        self.assertTrue(all(v.level is Level.SENTENCE for v in actual))

    def test_default_batches(self):
        calls = []
        backend = HashEmbedder(dims=2)

        class RecordingEmbedder:
            dims = 2

            def embed(self, texts, level):
                calls.append(len(texts))
                return backend.embed(texts, level)

        result = contextual_embed(self.chunks * 13, lambda c: [], RecordingEmbedder(),
                                  Level.BLOCK)
        self.assertEqual(len(result), 65)
        self.assertEqual(calls, [64, 1])
        self.assertTrue(all(v.level is Level.BLOCK for v in result))

    def test_empty_input_does_not_call_context_or_backend(self):
        def unexpected(*args):
            self.fail('empty input must not call context or backend')

        class Backend:
            dims = 2
            embed = unexpected

        self.assertEqual(contextual_embed([], unexpected, Backend(), Level.SECTION), [])

    def test_invalid_batch_size(self):
        for size, error in ((0, ValueError), (-1, ValueError), (True, TypeError),
                            (1.5, TypeError)):
            with self.subTest(size=size), self.assertRaises(error):
                contextual_embed([], lambda c: [], HashEmbedder(), Level.SENTENCE,
                                 batch_size=size)

    def test_backend_contract_is_validated(self):
        class BrokenBackend:
            dims = 2

            def embed(self, texts, level):
                return []

        with self.assertRaises(EmbedderError):
            contextual_embed(self.chunks, lambda c: [], BrokenBackend(), Level.SENTENCE)

    def test_context_errors_propagate(self):
        with self.assertRaises(ContextualPrefixError):
            contextual_embed(self.chunks, lambda c: ['bad\npath'], HashEmbedder(),
                             Level.SENTENCE)

    def test_arm_identifier(self):
        self.assertEqual(CONTEXTUAL_PREFIX, 'contextual_prefix')

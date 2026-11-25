"""Synthetic, offline acceptance checks for GE-01."""
import dataclasses
import importlib.util
import io
import json
import unittest

from generation.llm_client import LLMClient
from generation.run_record import SamplingParams


class ContextAssemblyTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('generation.context'),
                             'GE-01 context assembly is not implemented')
        from generation.context import Passage, Section, build_context
        return Passage, Section, build_context

    def fixture(self):
        Passage, Section, build = self.api()
        section = Section('s', 'Results', 'Full section café\ntext', tuple(
            Passage(str(i), 'text ' + str(i), 'evidence') for i in range(7)))
        return section, build

    def test_neighbours_limited_to_k_and_section(self):
        section, build = self.fixture()
        ctx = build(section, '3', k=2)
        self.assertEqual([p.id for p in ctx.before], ['1', '2'])
        self.assertEqual([p.id for p in ctx.after], ['4', '5'])
        self.assertEqual(ctx.passage.text, 'text 3')
        self.assertEqual(ctx.passage.move, 'evidence')
        self.assertEqual((ctx.section_id, ctx.section_title, ctx.section_text),
                         ('s', 'Results', 'Full section café\ntext'))
        with self.assertRaises(ValueError):
            build(section, 'other-section-passage')

    def test_first_last_singleton_and_zero(self):
        section, build = self.fixture()
        self.assertEqual(build(section, '0', k=99).before, ())
        self.assertEqual(len(build(section, '0', k=99).after), 6)
        self.assertEqual(build(section, '6', k=99).after, ())
        self.assertEqual(build(section, '3', k=0).before, ())
        self.assertEqual(build(section, '3', k=0).after, ())
        one = dataclasses.replace(section, passages=section.passages[:1])
        self.assertEqual(build(one, '0').after, ())

    def test_prompt_deterministic_and_immutable(self):
        section, build = self.fixture()
        a, b = build(section, '3'), build(section, '3')
        self.assertEqual(a.render_prompt().encode(), b.render_prompt().encode())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.section_text = 'changed'
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.passage.text = 'changed'
        self.assertIsInstance(a.before, tuple)

    def test_invalid_requests(self):
        section, build = self.fixture()
        for kwargs in ({'k': -1}, {'k': True}, {'k': 1.5},
                       {'max_chars': -1}, {'max_chars': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build(section, '3', **kwargs)
        with self.assertRaises(ValueError):
            build(section, 'missing')

    def test_budget_removes_farthest_first_then_following_on_ties(self):
        section, build = self.fixture()
        full = build(section, '3', k=2)
        # One character less drops the farthest following passage, then preceding.
        ctx = build(section, '3', k=2, max_chars=len(full.render_prompt()) - 1)
        self.assertEqual([p.id for p in ctx.before], ['1', '2'])
        self.assertEqual([p.id for p in ctx.after], ['4'])
        smaller = build(section, '3', k=2, max_chars=len(ctx.render_prompt()) - 1)
        self.assertEqual([p.id for p in smaller.before], ['2'])
        self.assertEqual([p.id for p in smaller.after], ['4'])
        self.assertLessEqual(len(smaller.render_prompt()), len(ctx.render_prompt()) - 1)

    def test_exact_core_budget_preserves_passage_and_section(self):
        section, build = self.fixture()
        core = build(section, '3', k=0)
        size = len(core.render_prompt())
        ctx = build(section, '3', k=99, max_chars=size)
        self.assertEqual(ctx, core)
        with self.assertRaises(ValueError):
            build(section, '3', max_chars=size - 1)

    def test_fake_transport_receives_exact_prompt(self):
        section, build = self.fixture()
        prompt = build(section, '3').render_prompt()
        requests = []
        def transport(request):
            requests.append(json.loads(request.data))
            return io.BytesIO(b'{"choices":[{"message":{"content":"rewrite"}}]}')
        client = LLMClient('http://localhost:8000/v1', 'fake', transport=transport)
        self.assertEqual(client.complete(prompt, SamplingParams(1, .5, 1., 32)), 'rewrite')
        self.assertEqual(requests[0]['messages'], [{'role': 'user', 'content': prompt}])

    def test_duplicate_ids_rejected_and_input_sequence_snapshotted(self):
        Passage, Section, build = self.api()
        items = [Passage('a', 'A', 'move')]
        section = Section('s', 'Title', 'A', items)
        items.clear()
        self.assertEqual(build(section, 'a').passage.text, 'A')
        with self.assertRaises(ValueError):
            build(Section('s', '', '', (section.passages[0],) * 2), 'a')

"""G-02.3 generation runner. LLM-built synthetic fixtures, a fake model and a fake critic only."""
import hashlib
import json
import os
import re
import tempfile
import unittest

from experiments import g02_generate as gen


def notes(n=5):
    return [{'section_id': f'{r}-s{i}', 'report_id': r, 'section_type': 'intro',
             'notes': f'{r} notes token{i} shared fact'} for i, r in enumerate(f'r{i}' for i in range(n))]


def pool():
    return [
        {'section_id': 'ex1', 'report_id': 'r1', 'section_type': 'intro',
         'text': 'Alpha beta gamma uniform words about shared fact.'},
        {'section_id': 'ex2', 'report_id': 'r2', 'section_type': 'intro',
         'text': 'Delta epsilon zeta uniform words about shared fact.'},
        {'section_id': 'ex3', 'report_id': 'r3', 'section_type': 'method',
         'text': 'Eta theta iota other words entirely.'},
    ]


def read(path):
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


class FakeModel:
    """Answers from the prompt: section id, exemplar markers and candidate variant."""
    model_id = 'fake-1'

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, temperature=None):
        self.prompts.append(prompt)
        sid = re.search(r'NOTES:\n(.+)', prompt).group(1)
        variant = re.search(r'Draft variant (\d+) of', prompt)
        if variant:
            return f'{sid} candidate {variant.group(1)}'
        arm = 'B' if 'EXEMPLARS:' in prompt else 'A'
        return f'{sid} arm {arm}'


class FakeCritic:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def __call__(self, candidate, context):
        self.calls.append((candidate, context))
        return self.scores.get(candidate, 0.0)


def critic_for_candidates(best):
    class C:
        def __call__(self, candidate, context):
            return 10.0 if candidate.endswith(f'candidate {best}') else float(candidate[-1])
    return C()


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'runs.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_three_records_per_section_and_no_same_report_exemplar(self):
        recs = notes(30)
        # Every section's own report contributes an exemplar that must never be used.
        big_pool = [{'section_id': f'{r}-ex{j}', 'report_id': r, 'section_type': 'intro',
                     'text': 'shared fact token words'}
                    for r in (f'r{i}' for i in range(30)) for j in range(2)]
        big_pool += [{'section_id': 'far', 'report_id': 'other', 'section_type': 'intro',
                      'text': 'shared fact token words'}]
        model = FakeModel()
        out = gen.generate(recs, big_pool, model, out_path=self.out,
                           critic=FakeCritic({}), k_exemplars=3, n_candidates=3)
        self.assertEqual(len(out), 90)
        by_section = {}
        for r in out:
            by_section.setdefault(r['section_id'], []).append(r['arm'])
        for sid, arms in by_section.items():
            self.assertEqual(sorted(arms), ['A', 'B', 'C'])
        for r in out:
            self.assertNotIn(r['report_id'], r['exemplar_report_ids'])
            self.assertNotIn(r['section_id'], r['exemplar_section_ids'])
        self.assertEqual(len(by_section), 30)
        s = gen.summarize(read(self.out), expected_sections=30)
        self.assertTrue(s['complete'], s)
        self.assertEqual(s['n_sections'], 30)
        self.assertEqual(s['missing'], [])
        self.assertEqual(s['same_report_exemplars'], [])

    def test_exemplars_come_from_other_reports_only(self):
        target = notes(1)[0]
        local_pool = [
            {'section_id': 'same-1', 'report_id': target['report_id'], 'section_type': 'intro',
             'text': 'shared fact token words'},
            {'section_id': 'same-2', 'report_id': target['report_id'], 'section_type': 'intro',
             'text': 'shared fact token words'},
            {'section_id': 'other-1', 'report_id': 'other', 'section_type': 'intro',
             'text': 'shared fact token words'},
            {'section_id': 'other-2', 'report_id': 'other2', 'section_type': 'intro',
             'text': 'shared fact token words'},
        ]
        out = gen.generate([target], local_pool, FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), k_exemplars=3, n_candidates=2)
        for r in out:
            self.assertTrue(set(r['exemplar_report_ids']) <= {'other', 'other2'}, r)
        self.assertEqual(len([r for r in out if r['arm'] == 'B'][0]['exemplar_section_ids']), 2)

    def test_injected_retriever_cannot_leak_the_same_report(self):
        target = notes(1)[0]

        def leaky(record, pool_):
            return [{'section_id': 'leak', 'report_id': record['report_id'],
                     'section_type': 'intro', 'text': 'same report text'}]

        out = gen.generate([target], [], FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), retriever=leaky, n_candidates=2)
        for r in out:
            self.assertEqual(r['exemplar_section_ids'], [])
            self.assertNotIn(r['report_id'], r['exemplar_report_ids'])

    def test_c_picks_the_critic_top_candidate(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=critic_for_candidates(3), k_exemplars=2, n_candidates=4)
        c = [r for r in out if r['arm'] == 'C'][0]
        self.assertTrue(c['text'].endswith('candidate 3'), c['text'])
        self.assertEqual(c['chosen_candidate'], 2)
        self.assertEqual(len(c['critic_scores']), 4)
        self.assertEqual(len(set(r['prompt_hash'] for r in out if r['arm'] == 'C')), 1)
        self.assertEqual(c['n_candidates'], 4)

    def test_c_critic_context_is_the_exemplar_prompt(self):
        target = notes(1)[0]
        critic = FakeCritic({})
        gen.generate([target], pool(), FakeModel(), out_path=self.out,
                     critic=critic, k_exemplars=2, n_candidates=2)
        contexts = {ctx for _, ctx in critic.calls}
        self.assertEqual(len(contexts), 1)
        self.assertIn('EXEMPLARS:', contexts.pop())

    def test_resume_skips_done_pairs(self):
        recs = notes(2)
        model = FakeModel()
        first = gen.generate(recs, pool(), model, out_path=self.out,
                             critic=FakeCritic({}), n_candidates=2)
        calls = len(model.prompts)
        second = gen.generate(recs, pool(), model, out_path=self.out,
                              critic=FakeCritic({}), n_candidates=2)
        self.assertEqual(len(first), 6)
        self.assertEqual(second, [])
        self.assertEqual(len(model.prompts), calls)
        self.assertEqual(len(read(self.out)), 6)

    def test_resume_regenerates_pre_r152_v1_records_and_skips_v2(self):
        # R152 changed arm C sampling; records written under 'g02.3-v1' are stale.
        self.assertEqual(gen.PROMPT_VERSION, 'g02.3-v2')
        recs = notes(1)
        model = FakeModel()
        first = gen.generate(recs, pool(), model, out_path=self.out,
                             critic=FakeCritic({}), n_candidates=2)
        stale = [dict(r, prompt_version='g02.3-v1') for r in first]
        with open(self.out, 'w', encoding='utf-8') as fh:
            for r in stale:
                fh.write(json.dumps(r) + '\n')
        regen = gen.generate(recs, pool(), model, out_path=self.out,
                             critic=FakeCritic({}), n_candidates=2)
        self.assertEqual(sorted(r['arm'] for r in regen), sorted(r['arm'] for r in first))
        self.assertTrue(all(r['prompt_version'] == 'g02.3-v2' for r in regen))
        calls = len(model.prompts)
        again = gen.generate(recs, pool(), model, out_path=self.out,
                             critic=FakeCritic({}), n_candidates=2)
        self.assertEqual(again, [])
        self.assertEqual(len(model.prompts), calls)

    def test_prompt_hash_model_and_text_recorded(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        for r in out:
            self.assertEqual(len(r['prompt_hash']), 64)
            self.assertEqual(r['model'], 'fake-1')
            self.assertIn(target['notes'], r['text'])
        a = [r for r in out if r['arm'] == 'A'][0]
        self.assertEqual(a['prompt_hash'],
                         hashlib.sha256(gen.build_prompt(target, 'A').encode()).hexdigest())

    def test_arm_a_omits_exemplars_and_arms_b_c_include_them(self):
        target = notes(1)[0]
        exemplars = [{'section_id': 'ex1', 'report_id': 'r9', 'section_type': 'intro',
                      'text': 'Unique exemplar wording.'}]
        a = gen.build_prompt(target, 'A')
        b = gen.build_prompt(target, 'B', exemplars)
        c = gen.build_prompt(target, 'C', exemplars, candidate=(0, 2))
        self.assertNotIn('Unique exemplar wording.', a)
        self.assertNotIn('EXEMPLARS:', a)
        for p in (a, b, c):
            self.assertIn(target['notes'], p)
            self.assertIn('intro', p)
        for p in (b, c):
            self.assertIn('Unique exemplar wording.', p)
            self.assertNotIn('r9', p)
        self.assertIn('Draft variant 1 of 2', c)
        self.assertNotEqual(gen.build_prompt(target, 'C', exemplars, candidate=(0, 2)),
                            gen.build_prompt(target, 'C', exemplars, candidate=(1, 2)))

    def test_summary_flags_a_missing_arm_and_duplicates(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        recs = [r for r in out if r['arm'] != 'B']
        s = gen.summarize(recs, expected_sections=1)
        self.assertFalse(s['complete'])
        self.assertEqual(s['missing'], [(target['section_id'], 'B')])
        s2 = gen.summarize(out + [out[0]], expected_sections=1)
        self.assertFalse(s2['complete'])
        self.assertEqual(s2['duplicates'], [(target['section_id'], 'A')])
        self.assertFalse(gen.summarize(out, expected_sections=2)['complete'])

    def test_summary_flags_same_report_exemplars(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        out[1]['exemplar_report_ids'] = [target['report_id']]
        s = gen.summarize(out, expected_sections=1)
        self.assertFalse(s['complete'])
        self.assertEqual(s['same_report_exemplars'], [target['section_id']])

    def _stale(self, rec):
        return {**rec, 'prompt_version': 'g02.3-v0', 'text': 'stale'}

    def test_summary_ignores_stale_prompt_version_records(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        stale = [self._stale(r) for r in out]
        s = gen.summarize(stale + out, expected_sections=1, model='fake-1',
                          prompt_version=gen.PROMPT_VERSION)
        self.assertTrue(s['complete'])
        self.assertEqual(s['duplicates'], [])
        self.assertEqual(s['n_records'], 3)
        other_model = [{**r, 'model': 'other'} for r in out]
        s2 = gen.summarize(other_model + out, expected_sections=1, model='fake-1',
                           prompt_version=gen.PROMPT_VERSION)
        self.assertTrue(s2['complete'])
        self.assertEqual(s2['duplicates'], [])

    def test_summary_flags_missing_current_arm_covered_only_by_stale(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        current = [r for r in out if r['arm'] != 'B']
        stale = [self._stale(r) for r in out]
        s = gen.summarize(stale + current, expected_sections=1, model='fake-1',
                          prompt_version=gen.PROMPT_VERSION)
        self.assertFalse(s['complete'])
        self.assertEqual(s['missing'], [(target['section_id'], 'B')])
        # A stale-only section does not count toward the target either.
        only_stale = gen.summarize(stale, expected_sections=1, model='fake-1',
                                   prompt_version=gen.PROMPT_VERSION)
        self.assertFalse(only_stale['complete'])
        self.assertEqual(only_stale['n_sections'], 0)

    def test_cli_summary_ignores_stale_records_in_out_file(self):
        notes_path = os.path.join(self.tmp.name, 'notes.jsonl')
        pool_path = os.path.join(self.tmp.name, 'pool.jsonl')
        with open(notes_path, 'w', encoding='utf-8') as fh:
            for r in notes(2):
                fh.write(json.dumps(r) + '\n')
        with open(pool_path, 'w', encoding='utf-8') as fh:
            for r in pool():
                fh.write(json.dumps(r) + '\n')
        with open(self.out, 'w', encoding='utf-8') as fh:
            for r in notes(2):
                for arm in gen.ARMS:
                    fh.write(json.dumps({'section_id': r['section_id'], 'report_id': r['report_id'],
                                         'arm': arm, 'model': 'fake-1',
                                         'prompt_version': 'g02.3-v0', 'text': 'stale',
                                         'exemplar_report_ids': []}) + '\n')
        rc = gen.main(['--notes', notes_path, '--pool', pool_path, '--out', self.out,
                       '--n-candidates', '2', '--expected-sections', '2'],
                      model=FakeModel(), critic=FakeCritic({}))
        self.assertEqual(rc, 0)
        self.assertEqual(len(read(self.out)), 12)

    def test_temperature_reaches_arm_c_model_calls(self):
        class TempModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.temps = []

            def __call__(self, prompt, temperature=None):
                self.temps.append(('C' if 'Draft variant' in prompt else 'AB', temperature))
                return super().__call__(prompt)

        m = TempModel()
        gen.generate(notes(1), pool(), m, out_path=self.out, critic=FakeCritic({}),
                     n_candidates=3, temperature=0.8)
        self.assertEqual([t for a, t in m.temps if a == 'C'], [0.8, 0.8, 0.8])
        self.assertEqual([t for a, t in m.temps if a == 'AB'], [None, None])
        c = [r for r in read(self.out) if r['arm'] == 'C'][0]
        self.assertEqual(c['temperature'], 0.8)

    def test_single_candidate_default_calls_model_with_prompt_only(self):
        class Strict(FakeModel):
            def __call__(self, prompt):  # no temperature kwarg accepted
                return super().__call__(prompt)

        out = gen.generate(notes(1), pool(), Strict(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=1)
        self.assertEqual(len(out), 3)
        self.assertNotIn('temperature', out[2])

    def _temp_model(self):
        class TempModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.temps = []

            def __call__(self, prompt, temperature=None):
                self.temps.append(('C' if 'Draft variant' in prompt else 'AB', temperature))
                return super().__call__(prompt)
        return TempModel()

    def test_default_arm_c_samples_at_default_temperature(self):
        self.assertEqual(gen.DEFAULT_C_TEMPERATURE, 0.7)
        m = self._temp_model()
        gen.generate(notes(1), pool(), m, out_path=self.out, critic=FakeCritic({}),
                     n_candidates=3)
        self.assertEqual([t for a, t in m.temps if a == 'C'], [0.7, 0.7, 0.7])
        self.assertEqual([t for a, t in m.temps if a == 'AB'], [None, None])
        recs = read(self.out)
        self.assertEqual([r for r in recs if r['arm'] == 'C'][0]['temperature'], 0.7)
        s = gen.summarize(recs, expected_sections=1)
        self.assertFalse(s['c_deterministic'])
        self.assertTrue(s['complete'])

    def test_explicit_temperature_zero_is_honoured_and_flagged(self):
        m = self._temp_model()
        gen.generate(notes(1), pool(), m, out_path=self.out, critic=FakeCritic({}),
                     n_candidates=2, temperature=0)
        self.assertEqual([t for a, t in m.temps if a == 'C'], [0, 0])
        recs = read(self.out)
        self.assertEqual([r for r in recs if r['arm'] == 'C'][0]['temperature'], 0)
        s = gen.summarize(recs, expected_sections=1)
        self.assertTrue(s['c_deterministic'])
        self.assertTrue(s['complete'])

    def test_c_deterministic_when_temperature_missing_and_ignores_other_runs(self):
        c = {'section_id': 's', 'report_id': 'r', 'arm': 'C', 'model': 'm',
             'prompt_version': 'v', 'n_candidates': 2}
        self.assertTrue(gen.summarize([c], expected_sections=None)['c_deterministic'])
        self.assertFalse(gen.summarize([{**c, 'n_candidates': 1}],
                                       expected_sections=None)['c_deterministic'])
        self.assertFalse(gen.summarize([{**c, 'prompt_version': 'old'}], expected_sections=None,
                                       prompt_version='v')['c_deterministic'])

    def test_cli_temperature_option(self):
        class TempModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.temps = []

            def __call__(self, prompt, temperature=None):
                self.temps.append(temperature)
                return super().__call__(prompt)

        notes_path = os.path.join(self.tmp.name, 'notes.jsonl')
        pool_path = os.path.join(self.tmp.name, 'pool.jsonl')
        with open(notes_path, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(notes(1)[0]) + '\n')
        with open(pool_path, 'w', encoding='utf-8') as fh:
            for r in pool():
                fh.write(json.dumps(r) + '\n')
        m = TempModel()
        rc = gen.main(['--notes', notes_path, '--pool', pool_path, '--out', self.out,
                       '--n-candidates', '2', '--expected-sections', '1',
                       '--temperature', '0.7'], model=m, critic=FakeCritic({}))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(m.temps, key=str), [0.7, 0.7, None, None])

    def test_lexical_retriever_ranks_overlap_and_is_deterministic(self):
        target = {'section_id': 't', 'report_id': 'rt', 'section_type': 'intro',
                  'notes': 'wavelet denoising spectral'}
        p = [{'section_id': 'b', 'report_id': 'r2', 'section_type': 'method',
              'text': 'wavelet transform'},
             {'section_id': 'a', 'report_id': 'r1', 'section_type': 'intro',
              'text': 'wavelet denoising'},
             {'section_id': 'c', 'report_id': 'r3', 'section_type': 'intro',
              'text': 'unrelated'}]
        got = gen.lexical_retriever(target, p, k=2)
        self.assertEqual([e['section_id'] for e in got], ['a', 'b'])
        self.assertEqual(got, gen.lexical_retriever(target, p, k=2))
        self.assertEqual(gen.lexical_retriever(target, p, k=0), [])
        self.assertEqual([e['section_id'] for e in gen.lexical_retriever(target, p, k=10)],
                         ['a', 'b', 'c'])

    def test_model_critic_parses_number_or_defaults_to_zero(self):
        class M:
            model_id = 'm'

            def __init__(self):
                self.replies = ['7', 'Score: 0.5', 'no number here', None]
                self.prompts = []

            def __call__(self, prompt):
                self.prompts.append(prompt)
                return self.replies.pop(0)

        critic = gen.model_critic(M())
        self.assertEqual(critic('text', 'context'), 7.0)
        self.assertEqual(critic('text', 'context'), 0.5)
        self.assertEqual(critic('text', 'context'), 0.0)
        self.assertEqual(critic('text', 'context'), 0.0)

    def test_summary_flags_mixed_models_without_filter(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        uniform = gen.summarize(out, expected_sections=1)
        self.assertTrue(uniform['complete'])
        self.assertEqual(uniform['models'], ['fake-1'])
        self.assertEqual(uniform['prompt_versions'], [gen.PROMPT_VERSION])
        mixed = [out[0], {**out[1], 'model': 'other'}, out[2]]
        s = gen.summarize(mixed, expected_sections=1)
        self.assertFalse(s['complete'])
        self.assertEqual(s['models'], ['fake-1', 'other'])

    def test_summary_flags_mixed_prompt_versions_without_filter(self):
        target = notes(1)[0]
        out = gen.generate([target], pool(), FakeModel(), out_path=self.out,
                           critic=FakeCritic({}), n_candidates=2)
        mixed = [out[0], self._stale(out[1]), out[2]]
        s = gen.summarize(mixed, expected_sections=1)
        self.assertFalse(s['complete'])
        self.assertEqual(s['prompt_versions'], ['g02.3-v0', gen.PROMPT_VERSION])

    def test_duplicate_section_id_raises_before_writing_second(self):
        first = notes(1)[0]
        second = {**first, 'notes': 'different notes for the duplicate'}
        with self.assertRaisesRegex(ValueError, re.escape(first['section_id'])):
            list(gen.iter_generate(iter([first, second]), pool(), FakeModel(),
                                   out_path=self.out, critic=FakeCritic({}), n_candidates=2))
        recs = read(self.out)
        self.assertEqual(len(recs), 3)
        self.assertFalse(any('different notes' in r['text'] for r in recs))

    def test_cli_duplicate_section_id_exits_2(self):
        import contextlib
        import io
        notes_path = os.path.join(self.tmp.name, 'notes.jsonl')
        pool_path = os.path.join(self.tmp.name, 'pool.jsonl')
        dup = notes(1)[0]
        with open(notes_path, 'w', encoding='utf-8') as fh:
            for r in (dup, dup):
                fh.write(json.dumps(r) + '\n')
        with open(pool_path, 'w', encoding='utf-8') as fh:
            for r in pool():
                fh.write(json.dumps(r) + '\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = gen.main(['--notes', notes_path, '--pool', pool_path, '--out', self.out,
                           '--n-candidates', '2', '--expected-sections', '1'],
                          model=FakeModel(), critic=FakeCritic({}))
        self.assertEqual(rc, 2)
        self.assertIn(dup['section_id'], err.getvalue())
        self.assertIn('duplicate', err.getvalue())

    def test_cli_runs_offline_with_injected_model(self):
        notes_path = os.path.join(self.tmp.name, 'notes.jsonl')
        pool_path = os.path.join(self.tmp.name, 'pool.jsonl')
        with open(notes_path, 'w', encoding='utf-8') as fh:
            for r in notes(2):
                fh.write(json.dumps(r) + '\n')
        with open(pool_path, 'w', encoding='utf-8') as fh:
            for r in pool():
                fh.write(json.dumps(r) + '\n')
        rc = gen.main(['--notes', notes_path, '--pool', pool_path, '--out', self.out,
                       '--model-name', 'fake-1', '--n-candidates', '2', '--expected-sections', '2'],
                      model=FakeModel(), critic=FakeCritic({}))
        self.assertEqual(rc, 0)
        self.assertEqual(len(read(self.out)), 6)
        self.assertEqual(len(gen.summarize(read(self.out), expected_sections=2)['missing']), 0)

    def _cli_next(self, *extra, n=2):
        import contextlib, io, shlex
        notes_path = os.path.join(os.path.dirname(self.out), 'notes.jsonl')
        pool_path = os.path.join(os.path.dirname(self.out), 'pool.jsonl')
        with open(notes_path, 'w', encoding='utf-8') as fh:
            for r in notes(2):
                fh.write(json.dumps(r) + '\n')
        with open(pool_path, 'w', encoding='utf-8') as fh:
            for r in pool():
                fh.write(json.dumps(r) + '\n')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gen.main(['--notes', notes_path, '--pool', pool_path, '--out', self.out,
                           '--n-candidates', '2', '--expected-sections', str(n), *extra],
                          model=FakeModel(), critic=FakeCritic({}))
        lines = buf.getvalue().splitlines()
        json.loads(lines[-1])  # summary stays the last line
        nxt = [shlex.split(l[len('next: '):]) for l in lines if l.startswith('next: ')]
        return rc, nxt

    def test_cli_prints_session_line_when_complete(self):
        rc, nxt = self._cli_next('--originals', '/priv/orig.jsonl')
        self.assertEqual(rc, 0)
        self.assertEqual(len(nxt), 1)
        argv = nxt[0]
        self.assertEqual(argv[:3], ['python', '-m', 'experiments.g02_session'])
        d = os.path.dirname(self.out)
        self.assertEqual(dict(zip(argv[3::2], argv[4::2])),
                         {'--generations': self.out, '--originals': '/priv/orig.jsonl',
                          '--out': os.path.join(d, 'g02_session.json'),
                          '--choices': os.path.join(d, 'g02_choices.jsonl')})

    def test_cli_session_line_placeholder_and_absent_when_incomplete(self):
        rc, nxt = self._cli_next()
        self.assertEqual(rc, 0)
        self.assertIn('ORIGINALS_JSONL', nxt[0])
        os.unlink(self.out)
        rc, nxt = self._cli_next(n=3)
        self.assertEqual(rc, 1)
        self.assertEqual(nxt, [])


if __name__ == '__main__':
    unittest.main()

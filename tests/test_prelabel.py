"""G-01.4 pre-label runner. LLM-built synthetic fixtures and a fake model callable only."""
import json
import os
import random
import tempfile
import unittest

from experiments import prelabel
from experiments.gates import g01
from service.genre import load_genre, version_key
from service.network_guard import NetworkGuardError

GENRE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic.json')
GENRE = load_genre(GENRE_PATH)
MOVE_IDS = [m['id'] for m in GENRE['moves']]


def items(n=6):
    return [{'sentence_id': f's{i}', 'doc_id': f'd{i % 2}', 'section_type': 'intro',
             'text': f'Synthetic sentence number {i}.', 'context': f'Context for {i}.'}
            for i in range(n)]


class FakeModel:
    """Answers each prompt from a script keyed by sentence text; records calls."""
    model_id = 'fake-1'

    def __init__(self, replies):
        self.replies = replies  # sentence index -> list of replies (consumed in order)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        for i, queue in self.replies.items():
            if f'Synthetic sentence number {i}.' in prompt and queue:
                return queue.pop(0)
        return MOVE_IDS[0]


def read(path):
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


class PrelabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'labels.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_prompt_lists_inventory_other_and_context(self):
        p = prelabel.build_prompt(items(1)[0], GENRE)
        for m in GENRE['moves']:
            self.assertIn(m['id'], p)
            self.assertIn(m['definition'], p)
        self.assertIn('other', p)
        self.assertIn('Context for 0.', p)
        self.assertIn('intro', p)

    def test_every_id_exactly_one_valid_label(self):
        model = FakeModel({1: [MOVE_IDS[-1]], 2: ['other'], 3: [f'Label: {MOVE_IDS[0]}']})
        recs = prelabel.prelabel(items(), GENRE, model, out_path=self.out)
        self.assertEqual([r['sentence_id'] for r in recs], [f's{i}' for i in range(6)])
        valid = set(MOVE_IDS) | {'other'}
        for r in read(self.out):
            self.assertIn(r['label'], valid)
            self.assertEqual(r['genre_version'], version_key(GENRE)['genre_version'])
            self.assertEqual(r['genre_hash'], version_key(GENRE)['genre_hash'])
            self.assertEqual(r['model'], 'fake-1')
            self.assertEqual(len(r['prompt_hash']), 64)
            self.assertFalse(r['invalid_reply'])
        s = prelabel.summarize(items(), read(self.out))
        self.assertTrue(s['exactly_one_label_each'])
        self.assertEqual(s['invalid_replies'], 0)
        self.assertEqual(sum(s['counts'].values()), 6)

    def test_invalid_replies_retried_then_other_flagged(self):
        both = f'{MOVE_IDS[0]} or {MOVE_IDS[1]}' if len(MOVE_IDS) > 1 else 'nonsense'
        model = FakeModel({0: ['banana', both, 'nope'],
                           1: ['banana', MOVE_IDS[0]]})
        recs = prelabel.prelabel(items(2), GENRE, model, out_path=self.out, max_retries=2)
        self.assertEqual(recs[0]['label'], 'other')
        self.assertTrue(recs[0]['invalid_reply'])
        self.assertEqual(recs[0]['attempts'], 3)
        self.assertEqual(recs[1]['label'], MOVE_IDS[0])
        self.assertFalse(recs[1]['invalid_reply'])
        self.assertEqual(recs[1]['attempts'], 2)
        s = prelabel.summarize(items(2), read(self.out))
        self.assertEqual(s['invalid_replies'], 1)

    def test_resume_skips_done_ids_no_duplicates(self):
        prelabel.prelabel(items(3), GENRE, FakeModel({}), out_path=self.out)
        model = FakeModel({})
        prelabel.prelabel(items(6), GENRE, model, out_path=self.out)
        self.assertEqual(len(model.prompts), 3)
        ids = [r['sentence_id'] for r in read(self.out)]
        self.assertEqual(sorted(ids), [f's{i}' for i in range(6)])
        self.assertTrue(prelabel.summarize(items(6), read(self.out))['exactly_one_label_each'])

    def test_resume_relabels_under_other_model(self):
        prelabel.prelabel(items(2), GENRE, FakeModel({}), out_path=self.out)
        other = FakeModel({})
        other.model_id = 'fake-2'
        prelabel.prelabel(items(2), GENRE, other, out_path=self.out)
        self.assertEqual(len(other.prompts), 2)

    def test_summary_flags_missing_and_duplicate(self):
        recs = [{'sentence_id': 's0', 'label': 'other', 'invalid_reply': False}] * 2
        s = prelabel.summarize(items(2), recs)
        self.assertFalse(s['exactly_one_label_each'])
        self.assertEqual(s['missing'], ['s1'])
        self.assertEqual(s['duplicates'], ['s0'])

    def test_output_loads_into_g01_as_llm_rater(self):
        prelabel.prelabel(items(), GENRE, FakeModel({1: ['other']}), out_path=self.out)
        llm = prelabel.llm_labels(read(self.out))
        expert = {f's{i}': MOVE_IDS[0] for i in range(6)}
        out = g01.run(random.Random(0), {'expert': expert, 'llm': llm,
                                         'labels': MOVE_IDS + ['other'], 'n_resamples': 10})
        self.assertEqual(out['pairing']['expert_llm']['paired'], 6)

    def test_prompt_contains_no_other_report_text(self):
        model = FakeModel({})
        prelabel.prelabel(items(4), GENRE, model, out_path=self.out)
        for i, p in enumerate(model.prompts):
            for j in range(4):
                if j != i:
                    self.assertNotIn(f'Synthetic sentence number {j}.', p)
                    self.assertNotIn(f'Context for {j}.', p)

    def test_local_model_refuses_non_loopback(self):
        with self.assertRaises(NetworkGuardError):
            prelabel.local_model('http://example.com:8000/v1')
        m = prelabel.local_model('http://127.0.0.1:9/v1', model='x')
        self.assertEqual(m.model_id, 'x')

    def test_local_model_sends_temperature(self):
        import io
        from unittest import mock
        sent = []

        def fake_open(req, timeout):
            sent.append(json.loads(req.data))
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': 'ok'}}]}).encode())

        call = prelabel.local_model('http://127.0.0.1:8080/v1', model='m')
        with mock.patch('urllib.request.urlopen', fake_open):
            self.assertEqual(call('p'), 'ok')
            self.assertEqual(call('p', temperature=0.9), 'ok')
        self.assertEqual([b['temperature'] for b in sent], [0, 0.9])
        self.assertEqual(call.model_id, 'm')

    def test_parse_reply(self):
        valid = MOVE_IDS + ['other']
        self.assertEqual(prelabel.parse_reply(f' {MOVE_IDS[0]}.\n', valid), MOVE_IDS[0])
        self.assertIsNone(prelabel.parse_reply('', valid))
        self.assertIsNone(prelabel.parse_reply('banana', valid))


if __name__ == '__main__':
    unittest.main()


class ResumeTruncationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'labels.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_truncated_last_line_relabels_only_missing(self):
        prelabel.prelabel(items(4), GENRE, FakeModel({}), out_path=self.out)
        with open(self.out, encoding='utf-8') as fh:
            lines = fh.readlines()
        with open(self.out, 'w', encoding='utf-8') as fh:
            fh.writelines(lines[:3])
            fh.write(lines[3][:len(lines[3]) // 2])  # torn tail, no newline
        model = FakeModel({})
        new = prelabel.prelabel(items(6), GENRE, model, out_path=self.out)
        self.assertEqual([r['sentence_id'] for r in new], ['s3', 's4', 's5'])
        self.assertEqual(len(model.prompts), 3)
        with open(self.out, encoding='utf-8') as fh:
            raw = fh.read().splitlines()
        good = []
        for line in raw:
            try:
                good.append(json.loads(line))
            except ValueError:
                continue
        self.assertEqual(len(raw) - len(good), 1)  # only the torn line is invalid
        self.assertEqual(sorted(r['sentence_id'] for r in good),
                         [f's{i}' for i in range(6)])


class CliTests(unittest.TestCase):
    def setUp(self):
        from experiments import annotation_sample as samp
        from experiments.splits import DocumentSplit
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.genre_path = os.path.join(os.path.dirname(__file__), 'fixtures',
                                       'genre_synthetic_sections.json')
        genre = load_genre(self.genre_path)
        self.docs_dir = os.path.join(root, 'docs')
        os.mkdir(self.docs_dir)
        docs = []
        for i in range(2):
            text = (f'Preamble {i} zero.\n\n## Findings\n\nInvented finding {i} ash. '
                    f'Invented finding {i} birch.\n')
            docs.append((f'r{i}.md', text))
            with open(os.path.join(self.docs_dir, f'r{i}.md'), 'w', encoding='utf-8') as fh:
                fh.write(text)
        manifest = samp.build_manifest(iter(docs), DocumentSplit(['t.md'], [d for d, _ in docs]),
                                       genre, n=3, repeat_fraction=0.5, seed=1)
        self.manifest = manifest
        self.manifest_path = os.path.join(root, 'manifest.json')
        with open(self.manifest_path, 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh)
        self.out = os.path.join(root, 'out.jsonl')
        self.genre = genre

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra):
        from unittest import mock
        model = lambda prompt: 'other'  # noqa: E731
        model.model_id = 'fake-cli'
        with mock.patch.object(prelabel, 'local_model', return_value=model), \
                mock.patch('builtins.print'):
            return prelabel.main(['--genre', self.genre_path, '--model-url',
                                  'http://127.0.0.1:1/v1', '--out', self.out, *extra])

    def test_manifest_documents_labels_exactly_manifest_ids(self):
        rc = self.run_cli('--manifest', self.manifest_path, '--documents', self.docs_dir)
        self.assertEqual(rc, 0)
        want = sorted(e['sentence_id'] for e in self.manifest['entries'])
        self.assertTrue(want)
        self.assertEqual(sorted(r['sentence_id'] for r in read(self.out)), want)

    def test_manifest_repeat_pass(self):
        rc = self.run_cli('--manifest', self.manifest_path, '--documents', self.docs_dir,
                          '--pass', 'repeat')
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(r['sentence_id'] for r in read(self.out)),
                         sorted(self.manifest['repeat']))

    def test_cli_manifest_path_uses_public_load_documents(self):
        from unittest import mock
        from experiments import annotate
        with mock.patch.object(annotate, 'load_documents',
                               wraps=annotate.load_documents) as spy:
            rc = self.run_cli('--manifest', self.manifest_path, '--documents', self.docs_dir)
        self.assertEqual(rc, 0)
        self.assertTrue(spy.called)

    def test_cli_manifest_resolves_documents_once_per_run(self):
        from unittest import mock
        from experiments import annotate
        with mock.patch.object(annotate, 'load_documents',
                               wraps=annotate.load_documents) as spy:
            rc = self.run_cli('--manifest', self.manifest_path, '--documents', self.docs_dir)
        self.assertEqual(rc, 0)
        self.assertEqual(spy.call_count, 1)

    def test_cli_items_file_read_once_per_run(self):
        from unittest import mock
        path = os.path.join(self.tmp.name, 'items.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for it in items(3):
                fh.write(json.dumps(it) + '\n')
        with mock.patch.object(prelabel, '_read_items', wraps=prelabel._read_items) as spy:
            self.assertEqual(self.run_cli('--items', path), 0)
        self.assertEqual(spy.call_count, 1)

    def test_items_jsonl_still_works(self):
        path = os.path.join(self.tmp.name, 'items.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for it in items(3):
                fh.write(json.dumps(it) + '\n')
        self.assertEqual(self.run_cli('--items', path), 0)
        self.assertEqual(len(read(self.out)), 3)

    def test_items_and_manifest_exclusive(self):
        with self.assertRaises(SystemExit), mock_stderr():
            self.run_cli('--items', 'x', '--manifest', self.manifest_path,
                         '--documents', self.docs_dir)

    def test_dict_context_rendered_readably(self):
        it = {'sentence_id': 'x', 'doc_id': 'd', 'section_type': 'findings', 'text': 'T.',
              'context': {'heading': 'Findings', 'previous': 'Before.', 'next': None}}
        p = prelabel.build_prompt(it, GENRE)
        self.assertIn('Findings', p)
        self.assertIn('Before.', p)
        self.assertNotIn("{'heading'", p)


def mock_stderr():
    import contextlib
    import io
    return contextlib.redirect_stderr(io.StringIO())


class FlakyModel:
    """Raises for scripted sentence indices; ``fail_times`` None means always."""
    model_id = FakeModel.model_id  # same id so resume applies

    def __init__(self, fail, fail_times=None):
        self.fail, self.fail_times, self.calls = set(fail), fail_times, {}

    def __call__(self, prompt):
        for i in self.fail:
            if f'Synthetic sentence number {i}.' in prompt:
                n = self.calls[i] = self.calls.get(i, 0) + 1
                if self.fail_times is None or n <= self.fail_times:
                    raise OSError(f'model down for {i}')
        return MOVE_IDS[0]


class ScriptedModel:
    """Returns or raises the scripted outcomes in order, one per call."""
    model_id = 'fake-1'

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        out = self.script.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class ModelErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'labels.jsonl')
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_raise_once_then_succeed_yields_normal_record(self):
        model = FlakyModel({1}, fail_times=1)
        recs = prelabel.prelabel(items(3), GENRE, model, out_path=self.out,
                                 sleep=self.sleeps.append)
        self.assertEqual([r['sentence_id'] for r in recs], ['s0', 's1', 's2'])
        self.assertEqual(recs[1]['label'], MOVE_IDS[0])
        self.assertFalse(recs[1]['invalid_reply'])
        self.assertEqual(len(self.sleeps), 1)
        self.assertGreater(self.sleeps[0], 0)

    def test_always_raising_reraises_after_flush_and_resume_skips(self):
        model = FlakyModel({2})
        with self.assertRaises(OSError):
            prelabel.prelabel(items(4), GENRE, model, out_path=self.out, max_retries=2,
                              sleep=self.sleeps.append)
        self.assertEqual(model.calls[2], 3)  # max_retries + 1 attempts
        self.assertEqual(len(self.sleeps), 2)
        self.assertEqual(self.sleeps, sorted(self.sleeps))  # non-decreasing backoff
        self.assertEqual([r['sentence_id'] for r in read(self.out)], ['s0', 's1'])
        ok = FakeModel({})
        recs = prelabel.prelabel(items(4), GENRE, ok, out_path=self.out)
        self.assertEqual([r['sentence_id'] for r in recs], ['s2', 's3'])
        self.assertEqual(len(ok.prompts), 2)
        self.assertTrue(prelabel.summarize(items(4), read(self.out))['exactly_one_label_each'])

    def test_budget_always_raising_calls_max_retries_plus_one(self):
        model = ScriptedModel([OSError('down')] * 10)
        with self.assertRaises(OSError):
            prelabel.prelabel(items(1), GENRE, model, out_path=self.out, max_retries=2,
                              sleep=self.sleeps.append)
        self.assertEqual(model.calls, 3)
        self.assertEqual(len(self.sleeps), 2)

    def test_budget_raise_then_invalid_replies_shares_one_budget(self):
        model = ScriptedModel([OSError('down')] + ['banana'] * 10)
        recs = prelabel.prelabel(items(1), GENRE, model, out_path=self.out, max_retries=2,
                                 sleep=self.sleeps.append)
        self.assertEqual(model.calls, 3)
        self.assertEqual(recs[0]['label'], 'other')
        self.assertTrue(recs[0]['invalid_reply'])
        self.assertEqual(recs[0]['attempts'], 3)
        self.assertEqual(len(self.sleeps), 1)  # invalid replies retry without sleep

    def test_budget_raise_then_valid_counts_both_calls(self):
        model = ScriptedModel([OSError('down'), MOVE_IDS[0]])
        recs = prelabel.prelabel(items(1), GENRE, model, out_path=self.out, max_retries=2,
                                 sleep=self.sleeps.append)
        self.assertEqual(recs[0]['label'], MOVE_IDS[0])
        self.assertFalse(recs[0]['invalid_reply'])
        self.assertEqual(recs[0]['attempts'], 2)
        self.assertEqual(model.calls, 2)

    def test_well_behaved_model_never_sleeps(self):
        prelabel.prelabel(items(3), GENRE, FakeModel({}), out_path=self.out,
                          sleep=self.sleeps.append)
        self.assertEqual(self.sleeps, [])


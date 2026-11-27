"""G-02.2 notes runner. LLM-built synthetic fixtures and a fake model only."""
import json
import os
import tempfile
import unittest

from experiments import g02_generate as gen
from experiments import g02_notes as notes
from experiments.splits import DocumentSplit, SplitLeakError
from service.network_guard import NetworkGuardError

GENRE = {'section_types': [
    {'id': 'intro', 'headings': ['Introduction']},
    {'id': 'method', 'headings': ['Method']},
    {'id': 'result', 'headings': ['Results']},
]}
BODY = ' '.join(f'word{i}' for i in range(50))


def doc(r):
    return (f'# Introduction\n\n{r} intro {BODY}\n\n# Method\n\n{r} method {BODY}\n\n'
            f'# Results\n\n{r} result {BODY}\n\n# Misc\n\nunmapped {BODY}\n\n# Method\n\nshort\n')


IDS = [f'r{i:02d}' for i in range(40)]
SPLIT = DocumentSplit(['train1'], IDS)


def docs(ids=IDS):
    return lambda: ((d, doc(d)) for d in ids)


class FakeModel:
    model_id = 'fake-notes'

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return '- a neutral fact\n- another fact'


def read(path):
    with open(path, encoding='utf-8') as fh:
        return [json.loads(l) for l in fh if l.strip()]


class SelectTest(unittest.TestCase):
    def test_train_doc_refused(self):
        with self.assertRaises(SplitLeakError):
            notes.select_sections(docs(IDS[:3] + ['train1']), SPLIT, GENRE, n=3)
        with self.assertRaises(SplitLeakError):
            notes.select_sections(docs(['stranger']), SPLIT, GENRE, n=1)

    def test_count_stratified_one_per_report_and_deterministic(self):
        a = notes.select_sections(docs(), SPLIT, GENRE, n=30, seed=1)
        self.assertEqual(len(a), 30)
        counts = {}
        for s in a:
            counts[s['section_type']] = counts.get(s['section_type'], 0) + 1
        self.assertEqual(counts, {'intro': 10, 'method': 10, 'result': 10})
        self.assertEqual(len({s['report_id'] for s in a}), 30)
        self.assertTrue(all(len(s['text'].split()) >= 40 for s in a))
        self.assertEqual(a, notes.select_sections(docs(), SPLIT, GENRE, n=30, seed=1))
        self.assertNotEqual(a, notes.select_sections(docs(), SPLIT, GENRE, n=30, seed=2))

    def test_reports_reused_only_when_needed(self):
        a = notes.select_sections(docs(IDS[:4]), SPLIT, GENRE, n=6, seed=0)
        self.assertEqual(len(a), 6)
        self.assertEqual(len({s['section_id'] for s in a}), 6)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, 'notes.jsonl')

    def test_records_feed_generate_and_resume(self):
        sections = notes.select_sections(docs(), SPLIT, GENRE, n=5, seed=0)
        model = FakeModel()
        recs = notes.extract_notes(sections, model, out_path=self.out)
        self.assertEqual(len(recs), 5)
        self.assertNotIn(sections[0]['text'], model.prompts[0].split('SECTION:')[0])
        for r in read(self.out):
            self.assertTrue({'section_id', 'report_id', 'section_type', 'notes'} <= set(r))
        again = notes.extract_notes(sections, model, out_path=self.out)
        self.assertEqual(again, [])
        self.assertEqual(len(model.prompts), 5)
        gout = os.path.join(self.tmp, 'gen.jsonl')
        g = list(gen.iter_generate(read(self.out), [], lambda p: 'x', out_path=gout,
                                   critic=lambda c, ctx: 0.0, n_candidates=1))
        self.assertEqual(len(g), 15)

    def test_leak_check(self):
        src = 'the pump failed after nine hundred hours of continuous running in the cold'
        sec = [{'section_id': 's1', 'text': src}, {'section_id': 's2', 'text': src}]
        recs = [{'section_id': 's1', 'notes': '- pump failed after nine hundred hours of continuous use'},
                {'section_id': 's2', 'notes': '- pump broke at 900 h; ran nonstop; cold site'}]
        review = notes.leak_review(sec, recs, n=6, sample_size=1, seed=0)
        self.assertEqual([f['section_id'] for f in review['flagged']], ['s1'])
        self.assertIn('pump failed after nine hundred hours', review['flagged'][0]['shared_ngrams'])
        self.assertEqual(len(review['expert_sample']), 1)


class CliTest(unittest.TestCase):
    def test_refuses_remote_model(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(NetworkGuardError):
                notes.main(['--corpus', d, '--genre', 'x', '--split-seed', '0',
                            '--test-fraction', '0.5', '--model-url', 'https://api.example.com/v1',
                            '--out', os.path.join(d, 'o.jsonl')])

    def test_cli_with_injected_model(self):
        with tempfile.TemporaryDirectory() as d:
            for r in IDS[:10]:
                with open(os.path.join(d, f'{r}.md'), 'w') as fh:
                    fh.write(doc(r))
            gpath = os.path.join(d, 'genre.json')
            with open(gpath, 'w') as fh:
                json.dump(GENRE, fh)
            out = os.path.join(d, 'out', 'notes.jsonl')
            os.makedirs(os.path.dirname(out))
            rc = notes.main(['--corpus', d, '--split-seed', '0', '--test-fraction', '0.5',
                             '--n', '3', '--out', out, '--genre', gpath], model=FakeModel(),
                            genre=GENRE)
            self.assertEqual(rc, 0)
            self.assertEqual(len(read(out)), 3)
            self.assertTrue(os.path.exists(out + '.review.json'))


    def test_cli_sections_out_writes_originals(self):
        with tempfile.TemporaryDirectory() as d:
            for r in IDS[:10]:
                with open(os.path.join(d, f'{r}.md'), 'w') as fh:
                    fh.write(doc(r))
            out = os.path.join(d, 'notes.jsonl')
            sec = os.path.join(d, 'originals.jsonl')
            argv = ['--corpus', d, '--split-seed', '0', '--test-fraction', '0.5', '--n', '3',
                    '--out', out, '--genre', 'g', '--sections-out', sec]
            self.assertEqual(notes.main(argv, model=FakeModel(), genre=GENRE), 0)
            rows = read(sec)
            self.assertEqual(len(rows), 3)
            self.assertEqual({tuple(sorted(r)) for r in rows},
                             {('report_id', 'section_id', 'section_type', 'text')})
            self.assertEqual({r['section_id'] for r in rows}, {r['section_id'] for r in read(out)})
            self.assertTrue(all(BODY in r['text'] for r in rows))
            with open(sec, 'w') as fh:
                fh.write('keep')
            with self.assertRaises(SystemExit) as cm:
                notes.main(argv, model=FakeModel(), genre=GENRE)
            self.assertEqual(cm.exception.code, 2)
            with open(sec) as fh:
                self.assertEqual(fh.read(), 'keep')

if __name__ == '__main__':
    unittest.main()

"""G-01.5 config builder for g01. Synthetic fixtures in tempdirs; no corpus text."""
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from experiments import annotation_sample as samp
from experiments import g01_inputs as gi
from experiments.annotate import AnnotateError
from experiments.gates import g01
from experiments.splits import DocumentSplit
from service.annotation_store import AnnotationStore
from service.genre import load_genre, version_key

GENRE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic_sections.json')
GENRE = load_genre(GENRE_PATH)
MOVES = [m['id'] for m in GENRE['moves']]
KEY = version_key(GENRE)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def doc(i):
    return '\n\n'.join([
        f'Preamble sentence {i} zero.', '## Findings',
        ' '.join(f'Invented finding {i} about {w}.' for w in ('ash', 'birch', 'cedar')),
        '## Conclusions', f'Invented conclusion {i} one. Invented conclusion {i} two.',
    ]) + '\n'


DOCS = [(f'r{i}.md', doc(i)) for i in range(3)]
SPLIT = DocumentSplit(['train.md'], [d for d, _ in DOCS])
MANIFEST = samp.build_manifest(iter(DOCS), SPLIT, GENRE, n=10_000, repeat_fraction=0.3, seed=1)
ENTRIES = MANIFEST['entries']
IDS = [e['sentence_id'] for e in ENTRIES]
REPEAT = list(MANIFEST['repeat'])


def lab(n):
    return (MOVES + ['other'])[n % (len(MOVES) + 1)]


def put(store, sid, label, pass_name='first', annotator='ann', retracted=False):
    e = next(e for e in ENTRIES if e['sentence_id'] == sid)
    rec = {'sentence_id': sid, 'annotator': annotator, 'timestamp': '2026-11-26T00:00:00Z',
           'pass': pass_name, 'doc_id': e['doc_id'], 'section_type': e['section_type']}
    if retracted:
        rec['retracted'] = True
    else:
        rec['label'] = label
    store.append(GENRE, rec)


def pre(sid, label, model='m1', key=KEY):
    return {'sentence_id': sid, 'doc_id': None, 'label': label, 'invalid_reply': False,
            'attempts': 1, 'model': model, 'prompt_hash': 'x', **key}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.store = AnnotationStore(os.path.join(d, 'labels.jsonl'))
        self.manifest_path = os.path.join(d, 'manifest.json')
        with open(self.manifest_path, 'w', encoding='utf-8') as fh:
            json.dump(MANIFEST, fh)
        self.pre_path = os.path.join(d, 'pre.jsonl')
        self.exp_expert, self.exp_llm, self.exp_rep = {}, {}, {}
        for n, sid in enumerate(IDS):
            put(self.store, sid, lab(n))
            self.exp_expert[sid] = lab(n)
        put(self.store, IDS[0], None, retracted=True)  # undone label -> absent
        del self.exp_expert[IDS[0]]
        put(self.store, IDS[1], lab(5), annotator='other-ann')  # other annotator ignored
        for n, sid in enumerate(REPEAT):
            put(self.store, sid, lab(n + 1), pass_name='repeat')
            self.exp_rep[sid] = lab(n + 1)
        old_key = {'genre_version': 'v-old', 'genre_hash': 'h-old'}
        with open(self.pre_path, 'w', encoding='utf-8') as fh:
            for n, sid in enumerate(IDS):
                fh.write(json.dumps(pre(sid, lab(n + 2))) + '\n')
                self.exp_llm[sid] = lab(n + 2)
                fh.write(json.dumps(pre(sid, 'zzz', key=old_key)) + '\n')
            fh.write(json.dumps(pre('not-in-manifest', 'other')) + '\n')
            fh.write(json.dumps(pre(IDS[2], 'other', model='m2')) + '\n')
            fh.write('{"sentence_id": "torn", "lab')  # torn final write
        self.doc_of = {e['sentence_id']: e['doc_id'] for e in ENTRIES}

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kw):
        kw.setdefault('annotator', 'ann')
        kw.setdefault('model_id', 'm1')
        return gi.build_config(self.store, GENRE, MANIFEST, self.pre_path, **kw)


class BuildConfigTest(Fixture):
    def test_maps_equal_expectations(self):
        cfg = self.build()
        self.assertEqual(cfg['expert'], self.exp_expert)
        self.assertEqual(cfg['expert_repeat'], self.exp_rep)
        self.assertEqual(cfg['llm'], self.exp_llm)
        self.assertEqual(cfg['doc_of'], self.doc_of)
        self.assertEqual(cfg['labels'], MOVES + ['other'])
        self.assertEqual(cfg['other_label'], 'other')
        self.assertNotIn(IDS[0], cfg['expert'])

    def test_passes_g01_run(self):
        out = g01.run(random.Random(0), self.build() | {'n_resamples': 10})
        self.assertIsInstance(out, dict)

    def test_no_repeat_key_when_empty(self):
        store = AnnotationStore(os.path.join(self.tmp.name, 'only_first.jsonl'))
        put(store, IDS[3], lab(0))
        cfg = gi.build_config(store, GENRE, MANIFEST, self.pre_path, model_id='m1')
        self.assertNotIn('expert_repeat', cfg)
        self.assertEqual(cfg['expert'], {IDS[3]: lab(0)})

    def test_duplicate_llm_label_raises(self):
        with open(self.pre_path, 'a', encoding='utf-8') as fh:
            fh.write('\n' + json.dumps(pre(IDS[4], 'other')) + '\n')
        with self.assertRaisesRegex(gi.G01InputsError, 'duplicate'):
            self.build()

    def test_two_models_without_model_id_raises(self):
        with self.assertRaisesRegex(gi.G01InputsError, 'model'):
            self.build(model_id=None)

    def test_two_annotators_without_annotator_raises(self):
        with self.assertRaisesRegex(gi.G01InputsError, 'annotator'):
            self.build(annotator=None)

    def test_version_mismatch_raises(self):
        bad = dict(MANIFEST, genre={'genre_version': 'v-old', 'genre_hash': 'h'})
        with self.assertRaises(AnnotateError):
            gi.build_config(self.store, GENRE, bad, self.pre_path)


class CliTest(Fixture):
    def args(self, out):
        return ['--store', self.store.path, '--genre', GENRE_PATH,
                '--manifest', self.manifest_path, '--prelabel', self.pre_path,
                '--annotator', 'ann', '--model-id', 'm1', '--out', out]

    def test_cli_writes_json_and_counts(self):
        out = os.path.join(self.tmp.name, 'cfg.json')
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = gi.main(self.args(out))
        self.assertEqual(rc, 0)
        with open(out, encoding='utf-8') as fh:
            cfg = json.load(fh)
        self.assertEqual(cfg['expert'], self.exp_expert)
        self.assertEqual(cfg['expert_repeat'], self.exp_rep)
        self.assertEqual(cfg['llm'], self.exp_llm)
        self.assertEqual(cfg['doc_of'], self.doc_of)
        text = buf.getvalue()
        paired = len(self.exp_expert.keys() & self.exp_llm.keys())
        for frag in (f'n expert: {len(self.exp_expert)}', f'n repeat: {len(self.exp_rep)}',
                     f'n llm: {len(self.exp_llm)}', f'n paired: {paired}'):
            self.assertIn(frag, text)

    def test_module_entrypoint(self):
        out = os.path.join(self.tmp.name, 'cfg2.json')
        r = subprocess.run([sys.executable, '-m', 'experiments.g01_inputs', *self.args(out)],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(out))


if __name__ == '__main__':
    unittest.main()

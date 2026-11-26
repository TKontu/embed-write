"""AN-01 annotation tool. LLM-built synthetic fixtures; no corpus text."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from experiments import annotate as an
from experiments import annotation_sample as samp
from experiments.splits import DocumentSplit
from service.annotation_store import AnnotationStore, RESERVED, _validated
from service.genre import load_genre

GENRE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic_sections.json')
GENRE = load_genre(GENRE_PATH)


def doc(i):
    return '\n\n'.join([
        f'Preamble sentence {i} zero.',
        '## Findings',
        ' '.join(f'Invented finding {i} about {w}.' for w in ('ash', 'birch', 'cedar', 'damson')),
        '## Conclusions',
        f'Invented conclusion {i} one. Invented conclusion {i} two.',
    ]) + '\n'


DOCS = [(f'r{i}.md', doc(i)) for i in range(3)]
SPLIT = DocumentSplit(['train.md'], [d for d, _ in DOCS])
MANIFEST = samp.build_manifest(iter(DOCS), SPLIT, GENRE, n=10_000, repeat_fraction=0.3, seed=1)
IDS = [e['sentence_id'] for e in MANIFEST['entries']]


def clock():
    return '2026-11-25T00:00:00Z'


class Script:
    def __init__(self, keys):
        self.keys = list(keys)
        self.out = []

    def input(self, prompt=''):
        if not self.keys:
            raise EOFError
        return self.keys.pop(0)

    def output(self, text):
        self.out.append(text)


def session(items, store, keys, pass_name='first', annotator='ann'):
    s = Script(keys)
    an.AnnotationSession(items, store, GENRE, annotator, pass_name,
                         input_fn=s.input, output_fn=s.output, clock=clock).run()
    return s


def items(**kw):
    return list(an.resolve_items(MANIFEST, iter(DOCS), GENRE, **kw))


class ResolveTests(unittest.TestCase):
    def test_ids_and_text_match_manifest(self):
        got = items()
        self.assertEqual([g['sentence_id'] for g in got], IDS)
        by_id = {g['sentence_id']: g for g in got}
        first_finding = [e for e in MANIFEST['entries'] if e['section_type'] == 'findings'][0]
        it = by_id[first_finding['sentence_id']]
        self.assertEqual(it['text'], 'Invented finding 0 about ash.')
        self.assertEqual(it['context']['heading'], 'Findings')
        self.assertIsNone(it['context']['previous'])
        self.assertEqual(it['context']['next'], 'Invented finding 0 about birch.')
        self.assertEqual(it['section_type'], 'findings')

    def test_version_mismatch_refused(self):
        bad = dict(MANIFEST, genre={'genre_version': 1, 'genre_hash': '0' * 64})
        with self.assertRaises(an.AnnotateError):
            list(an.resolve_items(bad, iter(DOCS), GENRE))

    def test_missing_id_named(self):
        bad = dict(MANIFEST, entries=MANIFEST['entries'] + [
            {'sentence_id': 'r1.md:deadbeefdeadbeef', 'doc_id': 'r1.md',
             'section_type': 'findings', 'ordinal': 99}])
        with self.assertRaisesRegex(an.AnnotateError, 'deadbeefdeadbeef'):
            list(an.resolve_items(bad, iter(DOCS), GENRE))
        with self.assertRaisesRegex(an.AnnotateError, 'r2.md'):
            list(an.resolve_items(MANIFEST, iter(DOCS[:2]), GENRE))

    def test_load_documents_public(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            for doc_id, text in DOCS:
                Path(d, doc_id).write_text(text, encoding='utf-8')
            got = list(an.load_documents(Path(d), MANIFEST))
            want = [(i, t) for i, t in DOCS if any(e['doc_id'] == i for e in MANIFEST['entries'])]
            self.assertEqual(got, want)
            Path(d, DOCS[0][0]).unlink()
            with self.assertRaisesRegex(an.AnnotateError, 'not in corpus'):
                list(an.load_documents(Path(d), MANIFEST))

    def test_repeat_only(self):
        got = items(only=an.pass_ids(MANIFEST, 'repeat'))
        self.assertEqual(sorted(g['sentence_id'] for g in got), MANIFEST['repeat'])
        self.assertTrue(MANIFEST['repeat'])


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = AnnotationStore(os.path.join(self.dir.name, 'labels.jsonl'))

    def tearDown(self):
        self.dir.cleanup()

    def lines(self):
        with open(self.store.path, encoding='utf-8') as fh:
            return [json.loads(l) for l in fh]

    def test_scripted_session_writes_valid_records(self):
        session(items()[:3], self.store, ['1', '2', 'o'])
        recs = self.lines()
        self.assertEqual([r['label'] for r in recs], ['alpha', 'beta', 'other'])
        for r in recs:
            _validated(GENRE, {k: v for k, v in r.items() if k not in RESERVED})
            self.assertEqual(r['pass'], 'first')
            self.assertNotIn('text', r)

    def test_screen_shows_moves_with_keys_and_context(self):
        s = session(items()[:1], self.store, ['q'])
        screen = '\n'.join(s.out)
        self.assertIn('[1] alpha', screen)
        self.assertIn('[2] beta', screen)
        self.assertIn('[o] other', screen)
        self.assertIn(items()[0]['text'], screen)

    def test_quit_then_resume_without_duplicates(self):
        its = items()
        session(its, self.store, ['1', 's', '2', 'q'])
        self.assertEqual(len(self.lines()), 2)
        s = session(its, self.store, ['1'] * len(its))
        recs = self.lines()
        ids = [r['sentence_id'] for r in recs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(IDS))
        # resume began at the skipped item (first unlabelled)
        self.assertEqual(recs[2]['sentence_id'], its[1]['sentence_id'])
        session(its, self.store, ['2'])  # nothing left: no prompt consumed, nothing written
        self.assertEqual(len(self.lines()), len(IDS))

    def test_undo_supersedes(self):
        its = items()[:2]
        session(its, self.store, ['1', 'u', '2', '1'])
        out = an.export(self.store, GENRE, MANIFEST, 'first')
        by_id = {r['sentence_id']: r['label'] for r in out}
        self.assertEqual(by_id[its[0]['sentence_id']], 'beta')
        self.assertEqual(len(self.store.history(its[0]['sentence_id'])), 2)

    def test_repeat_pass_separate_from_first(self):
        rep = items(only=an.pass_ids(MANIFEST, 'repeat'))
        session(items(), self.store, ['1'] * len(IDS))
        s = session(rep, self.store, ['2'] * len(rep), pass_name='repeat')
        first = an.export(self.store, GENRE, MANIFEST, 'first')
        repeat = an.export(self.store, GENRE, MANIFEST, 'repeat')
        self.assertEqual(len(first), len(IDS))
        self.assertTrue(all(r['label'] == 'alpha' for r in first))
        self.assertEqual(sorted(r['sentence_id'] for r in repeat), MANIFEST['repeat'])
        self.assertTrue(all(r['label'] == 'beta' for r in repeat))

    def test_export_validates_and_holds_no_text(self):
        session(items(), self.store, ['1', '2'] * len(IDS))
        out = an.export(self.store, GENRE, MANIFEST, 'first')
        for r in out:
            _validated(GENRE, {k: v for k, v in r.items() if k not in RESERVED})
            self.assertNotIn('text', r)
            self.assertNotIn('stale', r)
        blob = json.dumps(out)
        self.assertNotIn('Invented', blob)

    def test_cli_export(self):
        corpus = os.path.join(self.dir.name, 'corpus')
        os.mkdir(corpus)
        for d, t in DOCS:
            with open(os.path.join(corpus, d), 'w', encoding='utf-8') as fh:
                fh.write(t)
        mpath = os.path.join(self.dir.name, 'm.json')
        samp.write_manifest(mpath, MANIFEST)
        base = [sys.executable, '-m', 'experiments.annotate', '--manifest', mpath,
                '--corpus', corpus, '--genre', GENRE_PATH, '--store', self.store.path,
                '--annotator', 'ann']
        r = subprocess.run(base, input='1\n2\nq\n', capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        outp = os.path.join(self.dir.name, 'out.jsonl')
        r = subprocess.run(base + ['--export', outp], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(outp, encoding='utf-8') as fh:
            recs = [json.loads(l) for l in fh]
        self.assertEqual([x['label'] for x in recs], ['alpha', 'beta'])
        self.assertNotIn('Invented', r.stdout)


if __name__ == '__main__':
    unittest.main()


class PassHelperTests(unittest.TestCase):
    def test_first_pass_labels_survive_repeat_label(self):
        with tempfile.TemporaryDirectory() as d:
            store = AnnotationStore(os.path.join(d, 's.jsonl'))
            its = items()
            rep = MANIFEST['repeat'][0]
            session(its, store, ['1'] * len(its))
            session(items(only=set(MANIFEST['repeat'])), store, ['o'], pass_name='repeat')
            first = an.labels_for_pass(store, GENRE, 'first')
            self.assertEqual(len(first), len(its))
            by = {r['sentence_id']: r for r in first}
            self.assertEqual(by[rep]['label'], GENRE['moves'][0]['id'])
            self.assertEqual(by[rep]['pass'], 'first')
            repeat = an.labels_for_pass(store, GENRE, 'repeat', 'ann')
            self.assertEqual([(r['sentence_id'], r['label']) for r in repeat], [(rep, 'other')])
            self.assertEqual(an.labels_for_pass(store, GENRE, 'first', 'nobody'), [])
            with self.assertRaises(an.AnnotateError):
                an.labels_for_pass(store, GENRE, 'bogus')


class UndoRetractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AnnotationStore(os.path.join(self.tmp.name, 'l.jsonl'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_label_undo_quit_leaves_unlabelled(self):
        its = items()
        session(its, self.store, ['1', 'u', 'q'])
        self.assertEqual(an.export(self.store, GENRE, MANIFEST, 'first'), [])
        self.assertEqual(an.labels_for_pass(self.store, GENRE, 'first'), [])
        self.assertEqual(self.store.read(GENRE), [])
        s = session(its, self.store, ['q'])
        self.assertIn(its[0]['text'], s.out[0])

    def test_label_undo_relabel_exports_new_label(self):
        its = items()
        session(its, self.store, ['1', 'u', '2', 'q'])
        got = an.export(self.store, GENRE, MANIFEST, 'first')
        self.assertEqual([(r['sentence_id'], r['label']) for r in got],
                         [(its[0]['sentence_id'], GENRE['moves'][1]['id'])])

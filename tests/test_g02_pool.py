"""G-02.3 exemplar pool stage. LLM-built synthetic corpora only; no model, no network."""
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from experiments import g02_pool as pool
from experiments.splits import DocumentSplit, SplitLeakError, split_documents

GENRE = {'section_types': [
    {'id': 'intro', 'headings': ['Introduction']},
    {'id': 'method', 'headings': ['Method']},
]}
BODY = ' '.join(f'word{i}' for i in range(30))


def doc(r):
    return (f'# Introduction\n\n{r} intro {BODY}\n\n# Method\n\n{r} method {BODY}\n\n'
            f'# Misc\n\nunmapped {BODY}\n\n# Method\n\nshort\n')


class IterPoolTest(unittest.TestCase):
    split = DocumentSplit(['a', 'b'], ['t'])

    def test_train_only_records_skip_unknown_and_short(self):
        recs = list(pool.iter_pool(iter([('a', doc('a')), ('b', doc('b'))]), self.split, GENRE,
                                   min_words=20))
        self.assertEqual([r['section_id'] for r in recs], ['a#s1', 'a#s2', 'b#s1', 'b#s2'])
        self.assertEqual({r['section_type'] for r in recs}, {'intro', 'method'})
        self.assertEqual(set(recs[0]), {'section_id', 'report_id', 'section_type', 'text'})
        self.assertTrue(all('unmapped' not in r['text'] and r['text'] != 'short' for r in recs))

    def test_test_or_unassigned_id_refused(self):
        for bad in ('t', 'zz'):
            with self.subTest(bad=bad), self.assertRaises(SplitLeakError):
                list(pool.iter_pool(iter([('a', doc('a')), (bad, doc(bad))]), self.split, GENRE,
                                    min_words=20))

    def test_max_per_type(self):
        recs = list(pool.iter_pool(iter([('a', doc('a')), ('b', doc('b'))]), self.split, GENRE,
                                   min_words=20, max_per_type=1))
        self.assertEqual([r['section_id'] for r in recs], ['a#s1', 'a#s2'])

    def test_streams_one_document_at_a_time(self):
        consumed = []

        def gen():
            for d in ('a', 'b'):
                consumed.append(d)
                yield d, doc(d)
        it = pool.iter_pool(gen(), self.split, GENRE, min_words=20)
        next(it)
        self.assertEqual(consumed, ['a'])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.corpus = self.tmp / 'corpus'
        self.corpus.mkdir()
        for i in range(8):
            (self.corpus / f'r{i}.md').write_text(doc(f'r{i}'), encoding='utf-8')
        self.genre = self.tmp / 'genre.json'
        self.genre.write_text(json.dumps(GENRE), encoding='utf-8')
        self.out = self.tmp / 'pool.jsonl'

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def run_cli(self, *extra):
        argv = ['--corpus', str(self.corpus), '--genre', str(self.genre), '--split-seed', '0',
                '--test-fraction', '0.5', '--min-words', '20', '--out', str(self.out), *extra]
        o, e = StringIO(), StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            try:
                code = pool.main(argv, genre=GENRE)
            except SystemExit as x:
                code = x.code
        return code, o.getvalue(), e.getvalue()

    def test_writes_train_sections_0600(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        split = split_documents([f'r{i}.md' for i in range(8)], 0.5, 0)
        recs = [json.loads(l) for l in self.out.read_text(encoding='utf-8').splitlines()]
        self.assertEqual({r['report_id'] for r in recs}, set(split.train_ids))
        self.assertEqual(len(recs), 2 * len(split.train_ids))
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o600)
        self.assertEqual(json.loads(out.strip().splitlines()[-1])['written'], len(recs))

    def test_refuses_existing_output(self):
        self.out.write_text('keep\n', encoding='utf-8')
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('exists', err)
        self.assertEqual(self.out.read_text(encoding='utf-8'), 'keep\n')

    def test_leak_exits_2_and_leaves_no_file(self):
        def leaky(root, split):
            yield sorted(split.train_ids)[0], doc('x')
            yield sorted(split.test_ids)[0], doc('y')
        with mock.patch.object(pool, '_train_documents', leaky):
            code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('leak', err.lower())
        self.assertFalse(self.out.exists())

    def test_empty_pool_exits_2_and_leaves_no_file(self):
        code, out, err = self.run_cli('--min-words', '1000')
        self.assertEqual(code, 2)
        self.assertIn('empty', err.lower())
        errs = [l for l in err.splitlines() if l.startswith('error:')]
        self.assertEqual(len(errs), 1, err)
        self.assertIn('no training-split section', errs[0])
        self.assertEqual(out, '')
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()

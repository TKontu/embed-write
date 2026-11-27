"""G-02.4 session builder. LLM-built synthetic fixtures only; no corpus, model or network."""
import contextlib
import io
import json
import math
import os
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

from experiments import blind_session, blind_ui
from experiments import g02_session as gs

MODEL, VERSION = 'fake-gen', 'g02.3-v2'
COMPARISONS = ('A_vs_C', 'A_vs_B', 'C_vs_original')


def sid(i):
    return f'rep{i:02d}.md#s{i}'


def gen_records(n, *, model=MODEL, version=VERSION, arms=('A', 'B', 'C'), tag=''):
    for i in range(n):
        for arm in arms:
            yield {'section_id': sid(i), 'report_id': f'rep{i:02d}.md', 'section_type': 'intro',
                   'arm': arm, 'text': f'Synthetic {arm} draft {i}{tag}.', 'model': model,
                   'prompt_version': version, 'prompt_hash': 'x', 'exemplar_section_ids': [],
                   'exemplar_report_ids': ['other.md']}


def orig_records(n):
    for i in range(n):
        yield {'section_id': sid(i), 'report_id': f'rep{i:02d}.md', 'section_type': 'intro',
               'text': f'Synthetic original section {i}.'}


def write_jsonl(path, records):
    with open(path, 'w', encoding='utf-8') as fh:
        for r in records:
            fh.write(json.dumps(r) + '\n')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gen = self.p('gen.jsonl')
        self.orig = self.p('orig.jsonl')
        self.out = self.p('session.json')
        self.choices = self.p('choices.jsonl')

    def p(self, name):
        return os.path.join(self.tmp.name, name)

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = gs.main(['--generations', self.gen, '--originals', self.orig,
                              '--out', self.out, '--choices', self.choices, *extra])
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()


class BuildTest(Base):
    def test_complete_input_gives_3n_pairs_plus_repeats(self):
        n = 5
        write_jsonl(self.gen, gen_records(n))
        write_jsonl(self.orig, orig_records(n))
        rc, out, _ = self.run_cli('--seed', '1', '--repeat-fraction', '0.2', '--min-gap', '2')
        self.assertEqual(rc, 0)
        session = blind_session.load_session(self.out)
        base = [i for i in session if i.repeat_of is None]
        self.assertEqual(len(base), 3 * n)
        self.assertEqual(len(session) - len(base), math.ceil(0.2 * (3 * n)))
        self.assertEqual({i.comparison for i in session}, set(COMPARISONS))
        ids = {i.presentation.pair_id for i in base}
        self.assertEqual(ids, {f'{c}:{sid(k)}' for c in COMPARISONS for k in range(n)})
        arms = {c: set() for c in COMPARISONS}
        for i in session:
            arms[i.comparison] |= {i.presentation._left_arm, i.presentation._right_arm}
        self.assertEqual(arms, {'A_vs_C': {'A', 'C'}, 'A_vs_B': {'A', 'B'},
                                'C_vs_original': {'C', 'original'}})
        for i in session:
            if i.comparison == 'C_vs_original':
                self.assertIn('Synthetic original section', i.presentation.left
                              + i.presentation.right)

    def test_selects_model_and_rejects_ambiguity(self):
        n = 3
        write_jsonl(self.gen, [*gen_records(n), *gen_records(n, model='other', tag=' OTHER')])
        write_jsonl(self.orig, orig_records(n))
        rc, _, err = self.run_cli()
        self.assertEqual(rc, 2)
        self.assertIn('other', err)
        self.assertFalse(os.path.exists(self.out))
        rc, _, _ = self.run_cli('--model-id', MODEL)
        self.assertEqual(rc, 0)
        texts = ' '.join(i.presentation.left + i.presentation.right
                         for i in blind_session.load_session(self.out))
        self.assertNotIn('OTHER', texts)

    def test_selects_prompt_version(self):
        n = 2
        write_jsonl(self.gen, [*gen_records(n, version='old', tag=' OLD'), *gen_records(n)])
        write_jsonl(self.orig, orig_records(n))
        self.assertEqual(self.run_cli()[0], 2)
        rc, _, _ = self.run_cli('--prompt-version', VERSION)
        self.assertEqual(rc, 0)
        texts = ' '.join(i.presentation.left + i.presentation.right
                         for i in blind_session.load_session(self.out))
        self.assertNotIn('OLD', texts)

    def test_seed_reproducible(self):
        write_jsonl(self.gen, gen_records(4))
        write_jsonl(self.orig, orig_records(4))

        def shape():
            self.assertEqual(self.run_cli('--seed', '9', '--force')[0], 0)
            return [(i.item_id, i.comparison, i.repeat_of, i.presentation.pair_id,
                     i.presentation.left, i.presentation.right)
                    for i in blind_session.load_session(self.out)]
        self.assertEqual(shape(), shape())

    def test_stdout_has_no_text_and_has_serve_line(self):
        write_jsonl(self.gen, gen_records(3))
        write_jsonl(self.orig, orig_records(3))
        rc, out, err = self.run_cli('--seed', '1')
        self.assertEqual(rc, 0)
        self.assertNotIn('Synthetic', out + err)
        self.assertNotIn('#s', out)
        self.assertIn(f'python -m experiments.blind_ui {self.out} {self.choices}', out)

    def test_prints_draft_line_with_actual_paths(self):
        import shlex
        write_jsonl(self.gen, gen_records(3))
        write_jsonl(self.orig, orig_records(3))
        rc, out, _ = self.run_cli('--seed', '4')
        self.assertEqual(rc, 0)
        lines = [l for l in out.splitlines() if l.startswith('after judging: ')]
        self.assertEqual(len(lines), 1)
        argv = shlex.split(lines[0][len('after judging: '):])
        self.assertEqual(argv[:3], ['python', '-m', 'experiments.g02_draft'])
        self.assertEqual(dict(zip(argv[3::2], argv[4::2])),
                         {'--session': self.out, '--choices': self.choices, '--seed': '4',
                          '--text-model': MODEL,
                          '--out': os.path.join(self.tmp.name, 'g02_draft')})

    def test_docstring_privacy_and_caller(self):
        doc = gs.__doc__.lower()
        self.assertIn('private', doc)
        self.assertIn('production caller', doc)
        self.assertIn('g-02.4', doc)


class IncompleteTest(Base):
    def assert_refused(self, *extra):
        rc, out, err = self.run_cli(*extra)
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.out))
        self.assertNotIn('Synthetic', out + err)
        return err

    def test_missing_arm(self):
        recs = [r for r in gen_records(3) if not (r['section_id'] == sid(1) and r['arm'] == 'B')]
        write_jsonl(self.gen, recs)
        write_jsonl(self.orig, orig_records(3))
        self.assertIn(sid(1), self.assert_refused())
        rc, out, _ = self.run_cli('--allow-incomplete', '--seed', '1')
        self.assertEqual(rc, 0)
        self.assertIn('dropped', out)
        base = [i for i in blind_session.load_session(self.out) if i.repeat_of is None]
        self.assertEqual(len(base), 3 * 3 - 1)  # only A_vs_B for section 1 is dropped
        self.assertNotIn(f'A_vs_B:{sid(1)}', {i.presentation.pair_id for i in base})

    def test_missing_original(self):
        write_jsonl(self.gen, gen_records(3))
        write_jsonl(self.orig, [r for r in orig_records(3) if r['section_id'] != sid(2)])
        self.assertIn(sid(2), self.assert_refused())
        self.assertEqual(self.run_cli('--allow-incomplete')[0], 0)
        base = [i for i in blind_session.load_session(self.out) if i.repeat_of is None]
        self.assertEqual(len(base), 3 * 3 - 1)

    def test_empty_text(self):
        recs = list(gen_records(3))
        recs[0]['text'] = '  '
        write_jsonl(self.gen, recs)
        write_jsonl(self.orig, orig_records(3))
        self.assertIn(sid(0), self.assert_refused())

    def test_empty_original(self):
        write_jsonl(self.gen, gen_records(2))
        origs = list(orig_records(2))
        origs[1]['text'] = ''
        write_jsonl(self.orig, origs)
        self.assertIn(sid(1), self.assert_refused())

    def test_duplicate_section_arm(self):
        recs = list(gen_records(3))
        write_jsonl(self.gen, recs + [recs[4]])
        write_jsonl(self.orig, orig_records(3))
        self.assertIn(sid(1), self.assert_refused())
        self.assert_refused('--allow-incomplete')

    def test_summarize_not_complete_same_report_exemplar(self):
        recs = list(gen_records(2))
        recs[0]['exemplar_report_ids'] = [recs[0]['report_id']]
        write_jsonl(self.gen, recs)
        write_jsonl(self.orig, orig_records(2))
        self.assertIn(sid(0), self.assert_refused())

    def test_no_records(self):
        write_jsonl(self.gen, [])
        write_jsonl(self.orig, orig_records(2))
        self.assert_refused()


class OverwriteTest(Base):
    def setUp(self):
        super().setUp()
        write_jsonl(self.gen, gen_records(3))
        write_jsonl(self.orig, orig_records(3))

    def test_existing_session_needs_force(self):
        with open(self.out, 'w') as fh:
            fh.write('keep')
        self.assertEqual(self.run_cli()[0], 2)
        with open(self.out) as fh:
            self.assertEqual(fh.read(), 'keep')
        self.assertEqual(self.run_cli('--force')[0], 0)
        blind_session.load_session(self.out)

    def test_nonempty_choices_blocks_even_with_force(self):
        with open(self.out, 'w') as fh:
            fh.write('keep')
        with open(self.choices, 'w') as fh:
            fh.write('{"item_id": "item-0"}\n')
        rc, _, err = self.run_cli('--force')
        self.assertEqual(rc, 2)
        self.assertIn('orphan', err)
        with open(self.out) as fh:
            self.assertEqual(fh.read(), 'keep')

    def test_empty_choices_file_is_fine(self):
        open(self.choices, 'w').close()
        self.assertEqual(self.run_cli()[0], 0)


class ServeTest(Base):
    def test_blind_ui_serves_saved_session(self):
        write_jsonl(self.gen, gen_records(3))
        write_jsonl(self.orig, orig_records(3))
        self.assertEqual(self.run_cli('--seed', '3')[0], 0)
        session = blind_session.load_session(self.out)
        server = blind_ui.make_server(self.out, self.choices, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        with urllib.request.urlopen(url) as r:
            body = r.read().decode('utf-8')
        self.assertIn('Synthetic', body)
        forbidden = set(COMPARISONS) | {'original', 'repeat'}
        for i in session:
            forbidden |= {i.presentation.pair_id, i.presentation.key, i.item_id}
        forbidden |= {sid(k) for k in range(3)}
        for word in forbidden:
            self.assertNotIn(word, body.replace('Synthetic original section', ''))
        for label in ('>A<', '>B<', '>C<', '"A"', '"B"', '"C"'):
            self.assertNotIn(label, body)
        marker = 'name="nonce" value="'
        start = body.index(marker) + len(marker)
        nonce = body[start:body.index('"', start)]
        data = urllib.parse.urlencode(dict(nonce=nonce, choice='left', reason='')).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data)).read()
        with open(self.choices) as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec['comparison'], session[0].comparison)
        self.assertIn(rec['comparison'], COMPARISONS)


if __name__ == '__main__':
    unittest.main()

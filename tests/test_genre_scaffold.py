"""CO-13 genre-file scaffold: tests (LLM-built synthetic inputs only)."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from service.genre import load_genre, validate_genre
from service import genre_scaffold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, 'examples', 'demo', 'genre.json')


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = genre_scaffold.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'g.json')

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_validates(self):
        code, _, _ = run('new', self.out, '--name', 'my-genre')
        self.assertEqual(code, 0)
        obj = load_genre(self.out)
        self.assertEqual(obj['genre'], 'my-genre')
        self.assertEqual(len(obj['moves']), 3)
        self.assertTrue(any(k.startswith('_') for k in obj))
        for m in obj['moves']:
            for key in ('id', 'name', 'definition', 'near_miss'):
                self.assertIn('TODO', m[key])

    def test_new_moves_and_section_types(self):
        code, _, _ = run('new', self.out, '--name', 'g', '--moves', '5',
                         '--section-types', 'intro,results')
        self.assertEqual(code, 0)
        obj = validate_genre(json.load(open(self.out, encoding='utf-8')))
        self.assertEqual(len(obj['moves']), 5)
        self.assertEqual([t['id'] for t in obj['section_types']], ['intro', 'results'])

    def test_new_missing_parent_exits_2(self):
        out = os.path.join(self.tmp.name, 'nope', 'g.json')
        code, _, err = run('new', out, '--name', 'g')
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', err)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(out))

    def test_bad_move_count_rejected(self):
        for n in ('0', '11'):
            code, _, err = run('new', self.out, '--name', 'g', '--moves', n)
            self.assertNotEqual(code, 0)
            self.assertFalse(os.path.exists(self.out))

    def test_check_fresh_scaffold_lists_placeholders(self):
        run('new', self.out, '--name', 'g')
        code, out, _ = run('check', self.out)
        self.assertNotEqual(code, 0)
        self.assertIn('moves[0].id', out)
        self.assertIn('moves[2].definition', out)

    def test_check_filled_values_containing_todo_pass(self):
        obj = genre_scaffold.scaffold('g', 2)
        for i, m in enumerate(obj['moves'], 1):
            m['id'] = f'move{i}'
            m['name'] = f'Move {i}'
            m['definition'] = 'Writer checks the TODO list before reporting.'
            m['positive_examples'] = ['MASTODON reports grew.', 'See the TODO list.']
            m['near_miss'] = 'A todo-ish aside.'
        obj['legend']['colors'] = {'move1': '#111111', 'move2': '#222222'}
        with open(self.out, 'w', encoding='utf-8') as fh:
            fh.write(genre_scaffold.dumps(validate_genre(obj)))
        code, out, _ = run('check', self.out)
        self.assertEqual(code, 0, out)
        self.assertEqual(genre_scaffold.placeholders(obj), [])

    def test_check_fresh_scaffold_lists_every_marker(self):
        run('new', self.out, '--name', 'g', '--moves', '2', '--section-types', 'a')
        code, out, _ = run('check', self.out)
        self.assertEqual(code, 1)
        for f in ('moves[0].id', 'moves[0].name', 'moves[0].definition',
                  'moves[0].positive_examples[1]', 'moves[1].near_miss',
                  'legend.colors.TODO-move-1 (key)', 'legend.colors.TODO-move-2 (key)',
                  'section_types[0].name', 'section_types[0].headings[0]'):
            self.assertIn(f'  {f}\n', out)
        self.assertIn('16 placeholder', out)

    def test_check_demo_passes(self):
        code, _, _ = run('check', DEMO)
        self.assertEqual(code, 0)

    def test_check_invalid_file(self):
        with open(self.out, 'w', encoding='utf-8') as fh:
            fh.write('{"genre": "x"}')
        code, _, err = run('check', self.out)
        self.assertNotEqual(code, 0)
        self.assertIn('version', err)

    def test_overwrite_refused_without_force(self):
        with open(self.out, 'w', encoding='utf-8') as fh:
            fh.write('keep')
        code, _, err = run('new', self.out, '--name', 'g')
        self.assertNotEqual(code, 0)
        self.assertIn('--force', err)
        with open(self.out, encoding='utf-8') as fh:
            self.assertEqual(fh.read(), 'keep')

    def test_force_rerun_byte_identical(self):
        run('new', self.out, '--name', 'g', '--section-types', 'a,b')
        with open(self.out, 'rb') as fh:
            first = fh.read()
        code, _, _ = run('new', self.out, '--name', 'g', '--section-types', 'a,b', '--force')
        self.assertEqual(code, 0)
        with open(self.out, 'rb') as fh:
            self.assertEqual(fh.read(), first)

    def test_module_entrypoint(self):
        proc = subprocess.run([sys.executable, '-m', 'service.genre_scaffold', 'check', DEMO],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == '__main__':
    unittest.main()

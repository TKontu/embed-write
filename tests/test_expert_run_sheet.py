"""Keeps docs/expert-run-sheet.md true to the tools it names (R232, D-009 item 1(b)).

Every ``python -m experiments.X`` / ``python -m service.X`` command in the sheet must name a module
that exists, and every long flag it uses must appear in that module's (or subcommand's) argparse
``--help``. Rename a flag in a tool without updating the sheet and this test fails.
"""
import importlib.util
import re
import shlex
import subprocess
import sys
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / 'docs' / 'expert-run-sheet.md'
CMD = re.compile(r'python3? -m ((?:experiments|service)\.[A-Za-z_][\w.]*)([^\n`]*)')
SUBCOMMANDS = re.compile(r'\{([a-z_,-]+)\} \.\.\.')  # positional subparsers only, not choices


@lru_cache(maxsize=None)
def help_text(module: str, sub: str | None = None) -> str:
    args = [sys.executable, '-W', 'ignore', '-m', module] + ([sub] if sub else []) + ['--help']
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(f'{" ".join(args[3:])} failed: {proc.stderr.strip()[-400:]}')
    return proc.stdout


def commands(text: str) -> list[tuple[str, list[str]]]:
    return [(m.group(1), shlex.split(m.group(2))) for m in CMD.finditer(text)]


def accepted_flags(module: str, tokens: list[str]) -> tuple[str, set[str]]:
    top = help_text(module)
    subs = SUBCOMMANDS.search(top.split('\n\n')[0].replace('\n', ' '))
    label = module
    if subs:
        choices = subs.group(1).split(',')
        if not tokens or tokens[0] not in choices:
            raise AssertionError(f'{module}: needs a subcommand from {choices}, got {tokens[:1]}')
        top, label = help_text(module, tokens[0]), f'{module} {tokens[0]}'
    return label, set(re.findall(r'(?<![\w-])(--[a-z][\w-]*)', top))


def used_flags(tokens: list[str]) -> list[str]:
    return [t.split('=', 1)[0] for t in tokens if t.startswith('--')]


class ExpertRunSheetTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SHEET.exists(), f'{SHEET} missing')
        self.text = SHEET.read_text(encoding='utf-8')

    def test_sheet_names_every_tool_in_both_chains(self):
        found = {m for m, _ in commands(self.text)}
        for tool in ('intake', 'annotate', 'g01_draft', 'g02_notes', 'g02_generate',
                     'g02_session', 'blind_ui', 'g02_draft'):
            self.assertIn(f'experiments.{tool}', found)

    def test_every_module_exists_and_every_flag_is_accepted(self):
        cmds = commands(self.text)
        self.assertGreaterEqual(len(cmds), 8)
        for module, tokens in cmds:
            with self.subTest(module=module, tokens=tokens):
                self.assertIsNotNone(importlib.util.find_spec(module), f'{module} not found')
                label, accepted = accepted_flags(module, tokens)
                for flag in used_flags(tokens):
                    self.assertIn(flag, accepted, f'{label} does not accept {flag}')

    def test_sheet_ends_with_draft_and_expert_verdict(self):
        self.assertGreaterEqual(self.text.count('verdict owed to the expert'), 2)
        self.assertIn('DRAFT', self.text)

    def test_private_paths_are_marked_placeholders(self):
        self.assertIn('<PRIVATE:', self.text)
        self.assertNotIn('input/', self.text)  # no real corpus path

    def test_step_2_3_is_the_next_line_g02_notes_prints(self):
        import contextlib, io, json, os, tempfile
        from experiments import g02_notes
        genre = {'section_types': [{'id': 'intro', 'headings': ['Introduction']}]}
        body = ' '.join(f'w{i}' for i in range(50))
        (s1,) = re.findall(r'`(python -m [^`]+)`', self.step(1))  # names come from 2.1/2.2
        t1 = shlex.split(s1)
        notes_out, sections_out = t1[t1.index('--out') + 1], t1[t1.index('--sections-out') + 1]
        (s2,) = re.findall(r'`(python -m [^`]+)`', self.step(2))
        t2 = shlex.split(s2)
        pool_out = t2[t2.index('--out') + 1]

        class Fake:  # LLM-built synthetic fixture, no model
            model_id = 'fake'

            def __call__(self, prompt):
                return '- a fact'
        with tempfile.TemporaryDirectory() as d:
            corpus, g02 = os.path.join(d, 'c'), os.path.join(d, 'g')
            os.makedirs(corpus), os.makedirs(g02)
            for i in range(4):
                with open(os.path.join(corpus, f'r{i}.md'), 'w') as fh:
                    fh.write(f'# Introduction\n\nr{i} {body}\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = g02_notes.main(
                    ['--corpus', corpus, '--genre', 'G', '--split-seed', '0',
                     '--test-fraction', '0.5', '--n', '2', '--model-url', 'MU',
                     '--model-name', 'MN', '--out', notes_out.replace('<PRIVATE:G02>', g02),
                     '--sections-out', sections_out.replace('<PRIVATE:G02>', g02)],
                    model=Fake(), genre=genre)
            self.assertEqual(rc, 0)
            nxt = [l for l in buf.getvalue().splitlines() if l.startswith('next: ')][0]
            printed = [t.replace(g02, '<PRIVATE:G02>') for t in shlex.split(nxt[6:])]
        printed = [{'MU': '<MODEL_URL>', 'MN': '<MODEL_NAME>'}.get(t, t) for t in printed]
        step = self.text.split('### 2.3', 1)[1].split('### 2.4', 1)[0]
        (cmd,) = [c for c in re.findall(r'`(python -m [^`]+)`', step)]
        sheet = shlex.split(cmd)
        i = sheet.index('--expected-sections')
        self.assertEqual(sheet[i + 1], '30')  # the real run selects 30 sections
        printed[printed.index('--expected-sections') + 1] = '30'
        self.assertEqual(sheet, printed)
        for flag, want in (('--notes', notes_out), ('--originals', sections_out),
                           ('--pool', pool_out)):  # 2.3 consumes what 2.1/2.2 wrote
            with self.subTest(flag=flag):
                self.assertEqual(sheet[sheet.index(flag) + 1], want)

    def step(self, n):
        return self.text.split(f'### 2.{n}', 1)[1].split(f'### 2.{n + 1}', 1)[0]

    def test_step_2_4_is_the_next_line_g02_generate_prints(self):
        import contextlib, io, json, os, tempfile
        from experiments import g02_generate

        def fake(prompt, temperature=None):  # LLM-built synthetic fixture, no model
            return 'generated text'
        fake.model_id = 'fake'
        with tempfile.TemporaryDirectory() as d:
            g02 = os.path.join(d, 'g')
            os.makedirs(g02)
            notes, pool = os.path.join(g02, 'notes.jsonl'), os.path.join(g02, 'g02_pool.jsonl')
            with open(notes, 'w') as fh:
                for i in range(2):
                    fh.write(json.dumps({'section_id': f'r{i}-s', 'report_id': f'r{i}',
                                         'section_type': 'intro', 'notes': f'fact {i}'}) + '\n')
            with open(pool, 'w') as fh:
                fh.write(json.dumps({'section_id': 'ex', 'report_id': 'rx',
                                     'section_type': 'intro', 'text': 'fact words'}) + '\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = g02_generate.main(
                    ['--notes', notes, '--pool', pool,
                     '--out', os.path.join(g02, 'g02_generations.jsonl'),
                     '--originals', os.path.join(g02, 'originals.jsonl'),
                     '--expected-sections', '2', '--n-candidates', '2'],
                    model=fake, critic=lambda c, ctx: 0.0)
            self.assertEqual(rc, 0, buf.getvalue())
            nxt = [l for l in buf.getvalue().splitlines() if l.startswith('next: ')][0]
            printed = [t.replace(g02, '<PRIVATE:G02>') for t in shlex.split(nxt[6:])]
        (cmd,) = re.findall(r'`(python -m [^`]+)`', self.step(4))
        self.assertEqual(shlex.split(cmd), printed)

    def test_steps_2_5_and_2_6_use_the_session_and_choices_of_2_4(self):
        (cmd,) = re.findall(r'`(python -m [^`]+)`', self.step(4))
        t = shlex.split(cmd)
        session, choices = t[t.index('--out') + 1], t[t.index('--choices') + 1]
        (serve,) = re.findall(r'`(python -m [^`]+)`', self.step(5))
        self.assertEqual(shlex.split(serve)[3:], [session, choices])
        (draft,) = re.findall(r'`(python -m [^`]+)`', self.step(6))
        d = shlex.split(draft)
        self.assertEqual(d[d.index('--session') + 1], session)
        self.assertEqual(d[d.index('--choices') + 1], choices)
        for n in (4, 5, 6):  # prose too: no bare or /-prefixed short names left
            self.assertIsNone(re.search(r'(?<![\w-])(session\.json|choices\.jsonl)', self.step(n)), n)

    def test_step_2_6_is_the_after_judging_line_g02_session_prints(self):
        import contextlib, io, json, os, tempfile
        from experiments import g02_generate, g02_session

        def fake(prompt, temperature=None):  # LLM-built synthetic fixture, no model
            return 'generated text'
        fake.model_id = 'fake'
        with tempfile.TemporaryDirectory() as d:
            g02 = os.path.join(d, 'g')
            os.makedirs(g02)
            notes, pool = os.path.join(g02, 'notes.jsonl'), os.path.join(g02, 'g02_pool.jsonl')
            with open(notes, 'w') as fh:
                for i in range(2):
                    fh.write(json.dumps({'section_id': f'r{i}-s', 'report_id': f'r{i}',
                                         'section_type': 'intro', 'notes': f'fact {i}'}) + '\n')
            with open(pool, 'w') as fh:
                fh.write(json.dumps({'section_id': 'ex', 'report_id': 'rx',
                                     'section_type': 'intro', 'text': 'fact words'}) + '\n')
            with open(os.path.join(g02, 'originals.jsonl'), 'w') as fh:
                for i in range(2):
                    fh.write(json.dumps({'section_id': f'r{i}-s', 'text': f'original {i}'}) + '\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = g02_generate.main(
                    ['--notes', notes, '--pool', pool,
                     '--out', os.path.join(g02, 'g02_generations.jsonl'),
                     '--originals', os.path.join(g02, 'originals.jsonl'),
                     '--expected-sections', '2', '--n-candidates', '2'],
                    model=fake, critic=lambda c, ctx: 0.0)
            self.assertEqual(rc, 0, buf.getvalue())
            nxt = [l for l in buf.getvalue().splitlines() if l.startswith('next: ')][0]
            argv = shlex.split(nxt[6:])[3:]  # drop 'python -m experiments.g02_session'
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = g02_session.main(argv)
            self.assertEqual(rc, 0, buf.getvalue())
            line = [l for l in buf.getvalue().splitlines() if l.startswith('after judging: ')][0]
            printed = [t.replace(g02, '<PRIVATE:G02>') for t in shlex.split(line[15:])]
        (cmd,) = re.findall(r'`(python -m [^`]+)`', self.step(6))
        sheet = shlex.split(cmd)
        self.assertEqual(sheet[:3], printed[:3])
        for flag in ('--session', '--choices', '--seed', '--out'):  # not --text-model
            with self.subTest(flag=flag):
                self.assertEqual(sheet[sheet.index(flag) + 1], printed[printed.index(flag) + 1])
        out = sheet[sheet.index('--out') + 1].rsplit('/', 1)[1]
        self.assertIn(f'`{out}.json`', self.step(6))  # prose names g02_draft's real outputs
        self.assertIn(f'`{out}.md`', self.step(6))


class ExtractorSelfTest(unittest.TestCase):
    def test_bogus_flag_is_rejected(self):
        module, tokens = commands('`python -m experiments.g02_draft --session S --bogus-flag 1`')[0]
        _, accepted = accepted_flags(module, tokens)
        self.assertIn('--session', accepted)
        self.assertNotIn('--bogus-flag', accepted)

    def test_subcommand_help_is_used(self):
        _, accepted = accepted_flags('experiments.intake', ['run', 'SRC', 'OUT'])
        self.assertIn('--genre', accepted)


if __name__ == '__main__':
    unittest.main()

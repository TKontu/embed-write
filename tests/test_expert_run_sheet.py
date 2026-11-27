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

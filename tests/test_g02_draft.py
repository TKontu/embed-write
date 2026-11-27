"""G-02.5 draft result document. LLM-built synthetic fixtures in tempdirs; no real data."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import g01_draft, g02_draft
from tests.test_gate_g02 import fixture
from tests.test_preregistration import fixture_record


class G02DraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.prereg = os.path.join(d, 'prereg')
        os.mkdir(self.prereg)
        Path(self.prereg, 'g02.json').write_text(
            json.dumps({**fixture_record(), 'gate': 'g02'}), encoding='utf-8')
        s, lines = fixture()
        s[0]['left'] = 'SECRETSECTIONTEXT'
        lines[2] = lines[2].replace('"why"', '"SECRETREASON"')
        self.session = os.path.join(d, 'session.json')
        Path(self.session).write_text(json.dumps(s), encoding='utf-8')
        self.choices = os.path.join(d, 'choices.jsonl')
        Path(self.choices).write_text(''.join(lines), encoding='utf-8')
        self.out = os.path.join(d, 'out', 'g02-draft')

    def main(self, *extra, out=None, prereg=None):
        argv = ['--session', self.session, '--choices', self.choices, '--seed', '5',
                '--n-resamples', '50', '--out', out or self.out,
                '--preregistration-root', prereg or self.prereg, *extra]
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = g02_draft.main(argv)
        return code, o.getvalue(), e.getvalue()

    def test_end_to_end(self):
        code, out, err = self.main('--text-model', 'm-synth')
        self.assertEqual(code, 0, err)
        run = json.loads(Path(self.out + '.json').read_text(encoding='utf-8'))
        self.assertEqual(run['manifest']['gate'], 'g02')
        self.assertIn('preregistration', run['manifest'])
        md = Path(self.out + '.md').read_text(encoding='utf-8')
        self.assertIn('DRAFT', md)
        self.assertIn('Verdict: owed to the expert (G-02.5 [H])', md)
        self.assertIn('Basis:', md)
        self.assertIn('LLM-built by m-synth', md)
        self.assertIn('blind choices', md)
        for name in ('A_vs_C', 'A_vs_B', 'C_vs_original'):
            self.assertIn(f'| {name} |', md)
        self.assertIn('verdict_hint', md)
        self.assertIn('hint', md.lower())
        self.assertIn('consistency', md.lower())
        self.assertIn('non-empty reasons: 1', md)
        self.assertIn('proposed', md)
        for text in (md, out, Path(self.out + '.json').read_text()):
            self.assertNotIn('SECRETSECTIONTEXT', text)
            self.assertNotIn('SECRETREASON', text)
        low = md.lower()
        for word in ('passed', 'failed', 'inconclusive'):
            self.assertNotIn(word, low)
        # judge wording: the only "expert" is the owed-verdict line
        self.assertEqual(low.count('expert'), 1)
        self.assertIn('judge', low)

    def test_judge_is_expert_wording(self):
        code, _, err = self.main('--judge-is-expert')
        self.assertEqual(code, 0, err)
        md = Path(self.out + '.md').read_text(encoding='utf-8').lower()
        self.assertGreater(md.count('expert'), 1)

    def test_incomplete_run_said(self):
        lines = Path(self.choices).read_text().splitlines(keepends=True)
        Path(self.choices).write_text(''.join(lines[:3]), encoding='utf-8')
        code, _, err = self.main()
        self.assertEqual(code, 0, err)
        md = Path(self.out + '.md').read_text(encoding='utf-8')
        self.assertIn('INCOMPLETE', md)
        self.assertIn('unanswered: 3', md)

    def test_contradiction_exit_2_nothing_written(self):
        lines = Path(self.choices).read_text().splitlines(keepends=True)
        bad = json.loads(lines[0])
        bad['comparison'] = 'A_vs_B'
        Path(self.choices).write_text(json.dumps(bad) + '\n' + ''.join(lines[1:]))
        code, _, err = self.main()
        self.assertEqual(code, 2)
        self.assertIn('contradict', err)
        self.assertFalse(Path(self.out + '.md').exists())
        self.assertFalse(Path(self.out + '.json').exists())

    def test_session_not_list_of_objects_exit_2(self):
        for body in ('{"a": 1}', '[1, 2]', '"x"'):
            Path(self.session).write_text(body, encoding='utf-8')
            code, _, err = self.main()
            self.assertEqual(code, 2)
            self.assertTrue(err.startswith('error:'))
            self.assertNotIn('Traceback', err)
        self.assertFalse(Path(self.out + '.json').exists())

    def test_missing_preregistration_exit_2(self):
        os.remove(os.path.join(self.prereg, 'g02.json'))
        code, _, err = self.main()
        self.assertEqual(code, 2)
        self.assertIn('g02', err)
        self.assertIn('preregistration', err.lower())
        self.assertFalse(Path(self.out + '.json').exists())

    def test_results_dir_refused_before_running(self):
        stem = os.path.join(g01_draft.RESULTS_DIR, 'g02-refuse-test')
        os.remove(os.path.join(self.prereg, 'g02.json'))  # would fail later if it ran
        code, _, err = self.main(out=stem)
        self.assertEqual(code, 2)
        self.assertIn('experiments/results', err)
        self.assertFalse(Path(stem + '.json').exists())

    def test_reuses_g01_helpers(self):
        self.assertIs(g02_draft.DraftError, g01_draft.DraftError)


if __name__ == '__main__':
    unittest.main()

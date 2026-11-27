"""G-01.6 draft result document. LLM-built synthetic fixtures in tempdirs; no corpus text."""
import io
import json
import os
import tempfile
import unittest
import unittest.mock
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import g01_draft
from tests.test_g01_inputs import GENRE_PATH, Fixture
from tests.test_preregistration import fixture_record


class DraftFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.prereg = os.path.join(self.tmp.name, 'prereg')
        os.mkdir(self.prereg)
        Path(self.prereg, 'g01.json').write_text(
            json.dumps({**fixture_record(), 'gate': 'g01'}), encoding='utf-8')
        self.out = os.path.join(self.tmp.name, 'out', 'g01-draft')

    def argv(self, out=None, prereg=None):
        return ['--store', self.store.path,
                '--genre', GENRE_PATH, '--manifest', self.manifest_path,
                '--prelabel', self.pre_path, '--annotator', 'ann', '--model-id', 'm1',
                '--seed', '7', '--n-resamples', '20', '--out', out or self.out,
                '--preregistration-root', prereg or self.prereg]

    def main(self, argv):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = g01_draft.main(argv)
        return code, err.getvalue()


class DraftTest(DraftFixture):
    def test_end_to_end_writes_json_and_markdown(self):
        code, err = self.main(self.argv())
        self.assertEqual(code, 0, err)
        run = json.loads(Path(self.out + '.json').read_text(encoding='utf-8'))
        self.assertEqual(run['manifest']['gate'], 'g01')
        self.assertEqual(run['manifest']['seed'], 7)
        md = Path(self.out + '.md').read_text(encoding='utf-8')
        self.assertIn('DRAFT', md)
        self.assertIn('owed to the expert (G-01.6 [H])', md)
        self.assertIn('LLM-built', md)
        self.assertIn('kappa_expert_llm', md)
        self.assertIn('kappa_expert_self', md)
        kel = next(m for m in run['result']['metrics'] if m['metric'] == 'kappa_expert_llm')
        self.assertIn(str(kel['value']), md)
        self.assertIn('verdict_hint', md)
        self.assertIn('hint', md.lower())
        for word in ('passed', 'failed'):
            self.assertNotIn(word, md.lower())

    def test_draft_function_returns_run(self):
        run = g01_draft.draft(self.store, g01_draft.load_genre(GENRE_PATH),
                              json.loads(Path(self.manifest_path).read_text()), self.pre_path,
                              annotator='ann', model_id='m1', seed=1, out_path=self.out,
                              n_resamples=10, preregistration_root=self.prereg)
        self.assertIn('result', run)
        self.assertTrue(Path(self.out + '.md').exists())

    def _refused_stem(self, *via):
        # Target the directory the module under test actually guards (g01_draft.RESULTS_DIR),
        # not this test file's checkout: when tests from one checkout import experiments from
        # another (cwd), a ROOT-derived path is not refused and gets written into the repo.
        # A unique stem per run means stale files from elsewhere cannot affect the assertions;
        # addCleanup removes anything a regression would write.
        name = f'g01-draft-test-{os.getpid()}-{uuid.uuid4().hex}'
        results = g01_draft.RESULTS_DIR
        for suffix in ('.json', '.md'):
            self.addCleanup(lambda p=results / (name + suffix): p.unlink(missing_ok=True))
        target = results.parent.joinpath(*via, results.name, name) if via else results / name
        return target, [results / (name + '.json'), results / (name + '.md')]

    def test_results_dir_refused_nothing_written(self):
        target, written = self._refused_stem()
        code, err = self.main(self.argv(out=str(target)))
        self.assertEqual(code, 2)
        self.assertIn('experiments/results', err)
        for p in written:
            self.assertFalse(p.exists(), p)

    def test_results_dir_refused_via_dotdot(self):
        target, written = self._refused_stem('x', '..')
        self.assertIn('..', target.parts)
        code, _ = self.main(self.argv(out=str(target)))
        self.assertEqual(code, 2)
        for p in written:
            self.assertFalse(p.exists(), p)

    def _leaf_symlink_refused(self, suffix):
        # Hermetic: a temp dir stands in for experiments/results; the real one is never touched.
        fake = Path(self.tmp.name, 'fake-results').resolve()
        fake.mkdir()
        orig = g01_draft.RESULTS_DIR
        g01_draft.RESULTS_DIR = fake
        self.addCleanup(setattr, g01_draft, 'RESULTS_DIR', orig)
        os.makedirs(os.path.dirname(self.out))
        os.symlink(fake / ('x' + suffix), self.out + suffix)  # dangling leaf link into "results"
        code, err = self.main(self.argv())
        self.assertEqual(code, 2, err)
        self.assertIn('experiments/results', err)
        self.assertEqual(list(fake.iterdir()), [])
        other = '.json' if suffix == '.md' else '.md'
        self.assertFalse(os.path.lexists(self.out + other))

    def test_leaf_symlink_md_into_results_refused(self):
        self._leaf_symlink_refused('.md')

    def test_leaf_symlink_json_into_results_refused(self):
        self._leaf_symlink_refused('.json')

    def _fake_results(self):
        fake = Path(self.tmp.name, 'fake-results').resolve()
        fake.mkdir()
        orig = g01_draft.RESULTS_DIR
        g01_draft.RESULTS_DIR = fake
        self.addCleanup(setattr, g01_draft, 'RESULTS_DIR', orig)
        return fake

    def _loop_refused(self, link):
        fake = self._fake_results()
        os.makedirs(os.path.dirname(self.out))
        os.symlink(link, link)  # self-referential symlink loop
        code, err = self.main(self.argv())
        self.assertEqual(code, 2, err)
        self.assertNotIn('Traceback', err)
        self.assertIn('symlink loop', err)
        self.assertEqual(list(fake.iterdir()), [])
        out_dir = Path(os.path.dirname(self.out))
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()),
                         [os.path.basename(link)])

    def test_symlink_loop_stem_exit_2_nothing_written(self):
        self._loop_refused(self.out)

    def test_symlink_loop_leaf_json_exit_2_nothing_written(self):
        self._loop_refused(self.out + '.json')

    def test_symlink_loop_leaf_md_exit_2_nothing_written(self):
        self._loop_refused(self.out + '.md')

    def _nonleaf_loop_refused(self, simulate_313):
        fake = self._fake_results()
        loop = os.path.join(self.tmp.name, 'loop')
        os.symlink(loop, loop)  # self-referential loop as a NON-LEAF component of --out
        out = os.path.join(loop, 'sub', 'g01-draft')
        if simulate_313:
            # 3.13+ non-strict resolve() does not raise on loops: it returns the path with the
            # looping component left in place (here: not the leaf).
            orig = Path.resolve
            def fake_resolve(self, strict=False):
                try:
                    return orig(self, strict)
                except RuntimeError:
                    return Path(os.path.abspath(self))
            patcher = unittest.mock.patch.object(Path, 'resolve', fake_resolve)
            patcher.start()
            self.addCleanup(patcher.stop)
        code, err = self.main(self.argv(out=out))
        self.assertEqual(code, 2, err)
        self.assertNotIn('Traceback', err)
        self.assertIn('symlink loop', err)
        self.assertEqual(list(fake.iterdir()), [])
        self.assertEqual(sorted(os.listdir(self.tmp.name)).count('loop'), 1)
        self.assertTrue(os.path.islink(loop))

    def test_symlink_loop_nonleaf_exit_2_nothing_written(self):
        self._nonleaf_loop_refused(simulate_313=False)

    def test_symlink_loop_nonleaf_simulated_313_resolve_exit_2(self):
        self._nonleaf_loop_refused(simulate_313=True)

    def test_symlinked_results_dir_refused(self):
        # RESULTS_DIR itself is a symlink to a temp dir; an output resolving into the target
        # must still be refused (containment compares against the resolved RESULTS_DIR).
        target = Path(self.tmp.name, 'real-results').resolve()
        target.mkdir()
        link = Path(self.tmp.name, 'results-link')
        os.symlink(target, link)
        orig = g01_draft.RESULTS_DIR
        g01_draft.RESULTS_DIR = link
        self.addCleanup(setattr, g01_draft, 'RESULTS_DIR', orig)
        code, err = self.main(self.argv(out=str(target / 'g01-draft')))
        self.assertEqual(code, 2, err)
        self.assertIn('experiments/results', err)
        self.assertEqual(list(target.iterdir()), [])

    def test_missing_preregistration_exit_2(self):
        empty = os.path.join(self.tmp.name, 'empty')
        os.mkdir(empty)
        code, err = self.main(self.argv(prereg=empty))
        self.assertEqual(code, 2)
        self.assertIn('preregistration', err.lower())
        self.assertFalse(os.path.exists(os.path.dirname(self.out)))

    def test_unconfirmed_preregistration_exit_2(self):
        Path(self.prereg, 'g01.json').write_text(
            json.dumps({**fixture_record(), 'gate': 'g01', 'confirmed_by': ''}),
            encoding='utf-8')
        code, err = self.main(self.argv())
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', err)
        self.assertFalse(os.path.exists(self.out + '.md'))

    def test_docstring_unwired(self):
        self.assertIn('unwired by design until the real G-01.6 run (needs AN-03 labels and a '
                      'G-01.4 local-model run)', ' '.join(g01_draft.__doc__.split()))


if __name__ == '__main__':
    unittest.main()

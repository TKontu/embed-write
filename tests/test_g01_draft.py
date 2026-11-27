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

    def _lstat_raising(self, err):
        orig = os.lstat
        target = os.path.join(self.tmp.name, 'out')
        def fake(path, *a, **k):
            if os.fspath(path) == target:
                raise err
            return orig(path, *a, **k)
        patcher = unittest.mock.patch.object(os, 'lstat', fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lstat_oserror_names_strerror_not_loop(self):
        import errno
        self._lstat_raising(OSError(errno.EACCES, 'Permission denied'))
        with self.assertRaises(g01_draft.DraftError) as cm:
            g01_draft._resolve(self.out)
        self.assertIn('Permission denied', str(cm.exception))
        self.assertNotIn('symlink loop', str(cm.exception))

    def test_lstat_eloop_still_symlink_loop(self):
        import errno
        self._lstat_raising(OSError(errno.ELOOP, 'Too many levels of symbolic links'))
        with self.assertRaises(g01_draft.DraftError) as cm:
            g01_draft._resolve(self.out)
        self.assertIn('symlink loop', str(cm.exception))

    def _write_failure_exit_2(self, target, err):
        with unittest.mock.patch.object(Path, target, side_effect=err):
            code, out = self.main(self.argv())
        self.assertEqual(code, 2, out)
        self.assertNotIn('Traceback', out)
        self.assertIn('error:', out)
        return out

    def test_mkdir_oserror_exit_2(self):
        import errno
        out = self._write_failure_exit_2(
            'mkdir', OSError(errno.ENAMETOOLONG, 'File name too long'))
        self.assertIn('File name too long', out)

    def test_write_text_oserror_exit_2(self):
        import errno
        out = self._write_failure_exit_2(
            'write_text', OSError(errno.EACCES, 'Permission denied'))
        self.assertIn('Permission denied', out)

    def test_draft_oserror_is_drafterror(self):
        import errno
        with unittest.mock.patch.object(
                Path, 'write_text', side_effect=OSError(errno.ENOSPC, 'No space left')):
            with self.assertRaises(g01_draft.DraftError):
                self.main_draft()

    def main_draft(self):
        from service.genre import load_genre
        with open(self.manifest_path, encoding='utf-8') as fh:
            manifest = json.load(fh)
        return g01_draft.draft(self.store, load_genre(GENRE_PATH), manifest, self.pre_path,
                               annotator='ann', model_id='m1', seed=7, out_path=self.out,
                               n_resamples=20, preregistration_root=self.prereg)

    def _md_dir_failure(self, prior_json):
        os.makedirs(self.out + '.md')
        if prior_json is not None:
            Path(self.out + '.json').write_bytes(prior_json)
        code, out = self.main(self.argv())
        self.assertEqual(code, 2, out)
        self.assertNotIn('Traceback', out)
        self.assertIn(self.out + '.md', out)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))),
                         sorted(['g01-draft.md'] + (['g01-draft.json'] if prior_json else [])))
        return out

    def test_md_failure_preserves_prior_json(self):
        self._md_dir_failure(b'old json bytes\n')
        self.assertEqual(Path(self.out + '.json').read_bytes(), b'old json bytes\n')

    def test_md_failure_leaves_no_new_json(self):
        self._md_dir_failure(None)
        self.assertFalse(os.path.lexists(self.out + '.json'))

    def test_success_leaves_no_temp_files(self):
        code, err = self.main(self.argv())
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))),
                         ['g01-draft.json', 'g01-draft.md'])

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores chmod')
    def test_unwritable_out_dir_exit_2(self):
        ro = os.path.join(self.tmp.name, 'ro')
        os.mkdir(ro)
        os.chmod(ro, 0o500)
        try:
            code, out = self.main(self.argv(out=os.path.join(ro, 'sub', 'g01-draft')))
        finally:
            os.chmod(ro, 0o700)
        self.assertEqual(code, 2, out)
        self.assertNotIn('Traceback', out)
        self.assertIn('Permission denied', out)

    def test_comment_no_stale_eloop_claim(self):
        import inspect
        self.assertNotIn('ELOOP from lstat is a loop too', inspect.getsource(g01_draft._resolve))

    def test_docstring_unwired(self):
        self.assertIn('unwired by design until the real G-01.6 run (needs AN-03 labels and a '
                      'G-01.4 local-model run)', ' '.join(g01_draft.__doc__.split()))


class WritePairResidualTest(unittest.TestCase):
    # R220/A1: _write_pair residuals from R219/A1.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.json, self.md = self.d / 'x.json', self.d / 'x.md'

    def write(self):
        g01_draft._write_pair([(self.json, 'new json\n'), (self.md, 'new md\n')])

    def no_temps(self, allow=()):
        stray = [n for n in os.listdir(self.d)
                 if (n.endswith('.tmp') or n.endswith('.bak')) and n not in allow]
        self.assertEqual(stray, [])

    def test_redraft_keeps_prior_mode(self):
        self.json.write_text('old')
        os.chmod(self.json, 0o600)
        old = os.umask(0o022)
        try:
            self.write()
        finally:
            os.umask(old)
        self.assertEqual(self.json.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.md.stat().st_mode & 0o777, 0o644)
        self.no_temps()

    def test_double_fault_names_backup(self):
        self.json.write_text('old json')
        os.makedirs(self.md)
        real = os.replace

        def replace(src, dst):
            if str(src).endswith('.bak'):
                raise OSError(5, 'Input/output error')
            return real(src, dst)
        with unittest.mock.patch.object(g01_draft.os, 'replace', side_effect=replace):
            with self.assertRaises(g01_draft.DraftError) as cm:
                self.write()
        baks = [n for n in os.listdir(self.d) if n.endswith('.bak')]
        self.assertEqual(len(baks), 1)
        self.assertIn(str(self.d / baks[0]), str(cm.exception))
        self.assertEqual((self.d / baks[0]).read_text(), 'old json')
        self.no_temps(allow=baks)

    def test_prior_dangling_symlink_json_restored(self):
        os.symlink(self.d / 'nowhere', self.json)
        os.makedirs(self.md)
        with self.assertRaises(g01_draft.DraftError):
            self.write()
        self.assertTrue(os.path.islink(self.json))
        self.assertEqual(os.readlink(self.json), str(self.d / 'nowhere'))
        self.no_temps()

    def test_non_oserror_leaves_no_temps(self):
        real = Path.write_text
        calls = []

        def wt(path, text, *a, **k):
            calls.append(path)
            if len(calls) == 2:
                raise UnicodeEncodeError('utf-8', 'x', 0, 1, 'boom')
            return real(path, text, *a, **k)
        with unittest.mock.patch.object(Path, 'write_text', wt):
            with self.assertRaises((UnicodeEncodeError, g01_draft.DraftError)):
                self.write()
        self.assertEqual(os.listdir(self.d), [])


if __name__ == '__main__':
    unittest.main()

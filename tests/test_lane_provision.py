import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "lane_provision", Path(__file__).resolve().parents[1] / "scripts" / "lane_provision.py")
lp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lp)


class LaneProvisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "src"
        for d in ("editor", "docmodel"):
            (self.src / d / "node_modules").mkdir(parents=True)
            (self.tmp / "wt" / d).mkdir(parents=True)
        self.wt = self.tmp / "wt"
        self.link = self.wt / "editor" / "node_modules"
        self.target = (self.src / "editor" / "node_modules").resolve()

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=True)

    def test_create(self):
        code, _ = lp.provision(self.wt, self.src)
        self.assertEqual(code, 0)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(Path(os.readlink(self.link)), self.target)
        self.assertEqual(Path(os.readlink(self.wt / "docmodel" / "node_modules")),
                         (self.src / "docmodel" / "node_modules").resolve())

    def test_idempotent(self):
        lp.provision(self.wt, self.src)
        code, msg = lp.provision(self.wt, self.src)
        self.assertEqual(code, 0)
        self.assertIn("already", msg)

    def test_real_dir_refused(self):
        self.link.mkdir()
        (self.link / "keep").write_text("x")
        code, _ = lp.provision(self.wt, self.src)
        self.assertEqual(code, 1)
        self.assertFalse(self.link.is_symlink())
        self.assertTrue((self.link / "keep").exists())

    def test_wrong_link_refused(self):
        other = self.tmp / "other"
        other.mkdir()
        self.link.symlink_to(other)
        code, _ = lp.provision(self.wt, self.src)
        self.assertEqual(code, 1)
        self.assertEqual(Path(os.readlink(self.link)), other)
        self.assertTrue((self.wt / "docmodel" / "node_modules").is_symlink())  # sibling still provisioned

    def test_missing_source(self):
        (self.src / "docmodel" / "node_modules").rmdir()
        code, msg = lp.provision(self.wt, self.src)
        self.assertEqual(code, 2)
        self.assertIn("missing", msg)
        self.assertFalse(self.link.exists() or self.link.is_symlink())
        self.assertEqual(lp.main([str(self.wt), "--source", str(self.src)]), 2)

    def test_default_source_from_git_worktree(self):
        repo = self.tmp / "repo"
        def git(*a, cwd=repo):
            subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                           env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        repo.mkdir()
        git("init", "-q")
        for d in ("editor", "docmodel"):
            (repo / d).mkdir()
            (repo / d / "README").write_text("x")
        git("add", ".")
        git("commit", "-qm", "init")
        (repo / "editor" / "node_modules").mkdir()
        (repo / "docmodel" / "node_modules").mkdir()
        lane = self.tmp / "lane"
        git("worktree", "add", "-q", str(lane))
        code, _ = lp.provision(lane)
        self.assertEqual(code, 0)
        self.assertEqual(Path(os.readlink(lane / "editor" / "node_modules")),
                         (repo / "editor" / "node_modules").resolve())


if __name__ == "__main__":
    unittest.main()

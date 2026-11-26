"""A `.venv` symlink at the repo root must be ignored (lane worktrees symlink it)."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("git"), "git not available")
class GitignoreVenvSymlinkTest(unittest.TestCase):
    def test_venv_symlink_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            target = Path(tmp) / "real-venv"
            root.mkdir()
            target.mkdir()
            shutil.copyfile(REPO_ROOT / ".gitignore", root / ".gitignore")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            os.symlink(target, root / ".venv")
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=root, check=True, capture_output=True, text=True,
            ).stdout
            self.assertNotIn(".venv", status)
            check = subprocess.run(["git", "check-ignore", "-q", ".venv"], cwd=root)
            self.assertEqual(check.returncode, 0, ".venv symlink is not ignored")


if __name__ == "__main__":
    unittest.main()

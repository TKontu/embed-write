"""CLI for writing preregistration records (R242/A1, G-01.1); synthetic temp dirs only."""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from experiments import preregistration as prereg


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = prereg.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class PreregistrationCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def args(self, gate="g01", by="Synthetic Tester", extra=()):
        return ["confirm", gate, "--threshold", "kappa >= 0.6", "--metric", "Cohen kappa",
                "--confirmed-by", by, "--root", str(self.root), *extra]

    def test_success_record_loads(self):
        code, out, _ = run(self.args())
        self.assertEqual(code, 0)
        path = self.root / "g01.json"
        self.assertEqual(out.strip(), f"wrote {path}")
        record = prereg.load("g01", self.root)
        self.assertEqual(record["confirmed_by"], "Synthetic Tester")
        self.assertTrue(record["confirmed_at"].endswith("Z"))
        self.assertNotIn("recorded_commit", record)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(text, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        self.assertEqual([p.name for p in self.root.iterdir()], ["g01.json"])

    def test_recorded_commit_optional(self):
        self.assertEqual(run(self.args(extra=("--recorded-commit", "abc123")))[0], 0)
        self.assertEqual(prereg.load("g01", self.root)["recorded_commit"], "abc123")

    def test_missing_or_blank_confirmed_by(self):
        argv = self.args()
        i = argv.index("--confirmed-by")
        self.assertEqual(run(argv[:i] + argv[i + 2:])[0], 2)
        self.assertEqual(run(self.args(by="   "))[0], 2)
        self.assertEqual(run(self.args(by=""))[0], 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_bad_gate_id(self):
        for gate in ("../x", "g 01", "g01.json"):
            self.assertEqual(run(self.args(gate=gate))[0], 2, gate)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_file_refused_and_unchanged(self):
        path = self.root / "g01.json"
        path.write_text("original", encoding="utf-8")
        code, out, err = run(self.args())
        self.assertEqual(code, 1)
        self.assertIn("fixed once confirmed", err)
        self.assertEqual(out, "")
        self.assertEqual(path.read_text(encoding="utf-8"), "original")
        self.assertEqual([p.name for p in self.root.iterdir()], ["g01.json"])

    def test_dangling_symlink_refused_target_not_created(self):
        target = self.root / "elsewhere.json"
        (self.root / "g01.json").symlink_to(target)
        code, out, err = run(self.args())
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", err)
        self.assertFalse(target.exists())
        self.assertTrue((self.root / "g01.json").is_symlink())
        self.assertEqual([p.name for p in self.root.iterdir()], ["g01.json"])

    def test_concurrent_writer_refused(self):
        path = self.root / "g01.json"
        real_link = os.link

        def racing_link(src, dst, *a, **k):
            Path(dst).write_text("other", encoding="utf-8")
            return real_link(src, dst, *a, **k)

        with mock.patch.object(prereg.os, "link", racing_link):
            code, _, err = run(self.args())
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite", err)
        self.assertEqual(path.read_text(encoding="utf-8"), "other")
        self.assertEqual([p.name for p in self.root.iterdir()], ["g01.json"])

    def test_record_mode_0644(self):
        self.assertEqual(run(self.args())[0], 0)
        mode = stat.S_IMODE((self.root / "g01.json").stat().st_mode)
        self.assertEqual(mode, 0o644)

    def test_oserror_one_line_no_traceback(self):
        with mock.patch.object(prereg.os, "link", side_effect=PermissionError(13, "denied")):
            code, out, err = run(self.args())
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unwritable_root_one_line(self):
        root = self.root / "missing" / "nested"
        with mock.patch.object(prereg.tempfile, "mkstemp", side_effect=PermissionError(13, "denied")):
            code, out, err = run(self.args(extra=("--root", str(root))))
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(any(p.name.endswith(".tmp") for p in self.root.rglob("*")))

    def assert_not_dir_error(self, root, blocker):
        before = blocker.read_bytes()
        code, out, err = run(self.args(extra=("--root", str(root))))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("refusing to overwrite", err)
        self.assertNotIn("Traceback", err)
        self.assertIn("not a directory", err.lower())
        self.assertEqual(blocker.read_bytes(), before)

    def test_root_is_regular_file(self):
        blocker = self.root / "plain"
        blocker.write_text("synthetic\n")
        self.assert_not_dir_error(blocker, blocker)

    def test_root_parent_is_regular_file(self):
        blocker = self.root / "plain"
        blocker.write_text("synthetic\n")
        self.assert_not_dir_error(blocker / "child", blocker)

    def test_cleanup_unlink_error_does_not_mask_outcome(self):
        with mock.patch.object(prereg.os, "unlink", side_effect=PermissionError(1, "EPERM")):
            code, out, err = run(self.args())
        self.assertEqual(code, 0)
        self.assertIn("wrote", out)
        self.assertNotIn("Traceback", err)
        self.assertLessEqual(len(err.strip().splitlines()), 1, err)
        self.assertEqual(prereg.load("g01", self.root)["gate"], "g01")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "running as root: chmod 0555 does not block writes")
    def test_real_unwritable_root(self):
        root = self.root / "locked"
        root.mkdir()
        os.chmod(root, 0o555)
        self.addCleanup(os.chmod, root, 0o755)
        code, out, err = run(self.args(extra=("--root", str(root))))
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(root.iterdir()), [])

    def test_help_says_expert_only(self):
        code, out, _ = run(["confirm", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("Only the expert", out)


if __name__ == "__main__":
    unittest.main()

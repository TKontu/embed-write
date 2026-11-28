"""CLI for writing preregistration records (R242/A1, G-01.1); synthetic temp dirs only."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_help_says_expert_only(self):
        code, out, _ = run(["confirm", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("Only the expert", out)


if __name__ == "__main__":
    unittest.main()

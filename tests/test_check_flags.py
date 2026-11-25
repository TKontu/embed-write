"""Tests for the flag definitions and the CI flag check (X-02, invariant I6)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.gates.flags import DEFAULT_PATH, FlagError, check, load_flags
from experiments.gates.registry import load_registry

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_flags.py"

REGISTRY = """
[[gate]]
id = "G-01"
title = "First"
status = "{status}"
result_doc = "experiments/results/G-01.md"
flags_unlocked = []
"""

WRONG_FLAG = """
[[flag]]
name = "demo_feature"
gate = "G-01"
enabled = true
description = "Deliberately wrong: enabled while its gate is not passed."
"""


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO
    )


class FlagCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def registry(self, status):
        if status == "passed":
            doc = self.tmp / "experiments" / "results" / "G-01.md"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text("# G-01\n", encoding="utf-8")
        return self.write("registry.toml", REGISTRY.format(status=status))

    # (a) shipped files
    def test_shipped_files_pass(self):
        flags = load_flags(DEFAULT_PATH, load_registry())
        self.assertEqual([f for f in flags if f.enabled], [])
        self.assertEqual(check(flags, load_registry()), [])
        result = run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # (b) deliberately wrong flag fails CI
    def test_enabled_flag_with_pending_gate_exits_1(self):
        flags = self.write("flags.toml", WRONG_FLAG)
        for status in ("pending", "running", "failed", "waived"):
            with self.subTest(status=status):
                reg = self.registry(status)
                result = run_cli("--flags", str(flags), "--registry", str(reg), "--root", str(self.tmp))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("demo_feature", result.stderr)
                self.assertIn("G-01", result.stderr)
                self.assertIn(status, result.stderr)

    # (c) same flag, gate passed with result doc
    def test_enabled_flag_with_passed_gate_exits_0(self):
        flags = self.write("flags.toml", WRONG_FLAG)
        reg = self.registry("passed")
        result = run_cli("--flags", str(flags), "--registry", str(reg), "--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_disabled_flag_with_pending_gate_exits_0(self):
        flags = self.write("flags.toml", WRONG_FLAG.replace("enabled = true", "enabled = false"))
        reg = self.registry("pending")
        result = run_cli("--flags", str(flags), "--registry", str(reg), "--root", str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # (d) schema rules
    def test_schema_errors_exit_2_naming_flag_and_field(self):
        good = WRONG_FLAG.replace("enabled = true", "enabled = false")
        cases = {
            "unknown field": (good + 'owner = "x"\n', "demo_feature", "owner"),
            "unknown gate": (good.replace('"G-01"', '"G-99"'), "demo_feature", "gate"),
            "duplicate name": (good + good, "demo_feature", "name"),
            "bad name": (good.replace("demo_feature", "Demo-Feature"), "Demo-Feature", "name"),
            "missing name": (good.replace('name = "demo_feature"\n', ""), "#0", "name"),
            "enabled not bool": (good.replace("enabled = false", 'enabled = "yes"'), "demo_feature", "enabled"),
            "empty description": (
                good.replace('"Deliberately wrong: enabled while its gate is not passed."', '"  "'),
                "demo_feature",
                "description",
            ),
            "missing gate": (good.replace('gate = "G-01"\n', ""), "demo_feature", "gate"),
        }
        reg = self.registry("pending")
        for label, (text, flag, field) in cases.items():
            with self.subTest(label):
                path = self.write("flags.toml", text)
                with self.assertRaises(FlagError) as ctx:
                    load_flags(path, load_registry(reg, root=self.tmp))
                self.assertIn(flag, str(ctx.exception))
                self.assertIn(f"field {field}", str(ctx.exception))
                result = run_cli("--flags", str(path), "--registry", str(reg), "--root", str(self.tmp))
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(flag, result.stderr)
                self.assertIn(field, result.stderr)

    def test_flag_key_must_be_table_array(self):
        path = self.write("flags.toml", 'flag = "nope"\n')
        result = run_cli("--flags", str(path), "--registry", str(self.registry("pending")), "--root", str(self.tmp))
        self.assertEqual(result.returncode, 2)

    # (e) nightly wiring
    def test_nightly_runs_flag_check(self):
        text = (REPO / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
        self.assertIn("python3 scripts/check_flags.py", text)


if __name__ == "__main__":
    unittest.main()

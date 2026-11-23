import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from analysis import signal_gates as sg
from analysis import signals
from analysis.signals import SignalKind

PASS_MD = "# G-01 — q\n\n## Verdict\npassed — operator\n\n## Fallback taken\nnone\n"
FAIL_MD = "# G-01 — q\n\n## Verdict\nfailed — operator\n"


def _kind(name, gate):
    return SignalKind(name, gate, name.title(), "def.", "limits.")


class RegistryRestore(unittest.TestCase):
    def setUp(self):
        saved = dict(signals._REGISTRY)
        self.addCleanup(lambda: (signals._REGISTRY.clear(), signals._REGISTRY.update(saved)))


class DefaultsTest(unittest.TestCase):
    def test_defaults_cover_every_registered_kind_and_are_off(self):
        kinds = signals.registered_kinds()
        flags = sg.default_flags()
        self.assertEqual(set(flags), {k.name for k in kinds})
        for k in kinds:
            self.assertFalse(flags[k.name].enabled)
            self.assertEqual(flags[k.name].gates, k.gate)
        self.assertEqual(sg.check(flags, set()), [])


class CheckTest(RegistryRestore):
    def test_enabled_without_pass_is_violation(self):
        flags = sg.default_flags()
        flags["move"] = replace(flags["move"], enabled=True)
        v = sg.check(flags, {"G-01"})  # G-04 missing
        self.assertEqual(len(v), 1)
        self.assertIn("G-04", v[0])

    def test_registered_kind_without_flag_is_violation(self):
        flags = sg.default_flags()
        signals.register_kind(_kind("probe", ("G-99",)))
        v = sg.check(flags, set())
        self.assertEqual(v, ["registered kind 'probe' has no flag"])

    def test_flag_for_unregistered_kind_is_violation(self):
        flags = sg.default_flags()
        flags["ghost"] = sg.SignalFlag("ghost", ("G-01",), False)
        self.assertEqual(sg.check(flags, set()), ["flag 'ghost' is for an unregistered kind"])

    def test_enabled_with_all_gates_passed_is_clean(self):
        flags = {n: replace(f, enabled=True) for n, f in sg.default_flags().items()}
        all_gates = {g for k in signals.registered_kinds() for g in k.gate}
        self.assertEqual(sg.check(flags, all_gates), [])


class MarkerTest(unittest.TestCase):
    def test_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "G-01.md").write_text(PASS_MD)
            (p / "G-04.md").write_text(FAIL_MD)
            (p / "G-05.md").write_text("passed\n")  # no Verdict section
            self.assertEqual(sg.passed_gates(["G-01", "G-04", "G-05", "G-06"], p), {"G-01"})

    def test_template_is_not_a_pass(self):
        self.assertFalse(sg.gate_passed(sg.DEFAULT_RESULTS_DIR / "TEMPLATE.md"))


class CliTest(RegistryRestore):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            return sg.main(list(argv))

    def test_clean_exit_0(self):
        self.assertEqual(self.run_cli(), 0)

    def test_violation_exit_1(self):
        bad = {"move": sg.SignalFlag("move", ("G-01", "G-04"), True)}
        with mock.patch.object(sg, "default_flags", return_value=bad):
            self.assertEqual(self.run_cli(), 1)

    def test_bad_input_exit_2(self):
        self.assertEqual(self.run_cli("--results", "/nonexistent/dir"), 2)
        self.assertEqual(self.run_cli("--bogus"), 2)
        signals.register_kind(_kind("probe", ("bad-gate",)))
        self.assertEqual(self.run_cli(), 2)


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from experiments import nightly
from experiments.gates import sample


def _gate(gate_id, fn):
    fn.gate_id = gate_id
    return fn


def _flaky():
    calls = {"n": 0}

    def run(rng, config):
        calls["n"] += 1
        return {"value": calls["n"]}

    return _gate("sample", run)


class NightlyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def write(self, name, data):
        with open(self.path(name), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return self.path(name)

    def run_main(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = nightly.main(argv, **kw)
        return code, out.getvalue(), err.getvalue()

    def test_sample_runs_and_passes(self):
        code, out, _ = self.run_main([])
        self.assertEqual(code, 0)
        summary = json.loads(out)
        g = summary["gates"]["sample"]
        self.assertEqual(g["status"], "passed")
        self.assertEqual(g["rerun_reasons"], ["modelVersion", "inventoryVersion", "method"])
        self.assertEqual(g["notes"], [])

    def test_previous_same_descriptor_needs_no_rerun_reason(self):
        first = self.path("s1.json")
        self.assertEqual(self.run_main(["--out", first])[0], 0)
        code, out, _ = self.run_main(["--previous", first])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["gates"]["sample"]["rerun_reasons"], [])

    def test_regression_disables_bound_flag_and_exits_1(self):
        flags = self.write("flags.json", {
            "feat": {"gate": "sample", "enabled": True, "reason": ""},
            "other": {"gate": "G-02", "enabled": True, "reason": ""},
        })
        code, out, _ = self.run_main(["--flags", flags], gates=[(_flaky(), {})])
        self.assertEqual(code, 1)
        g = json.loads(out)["gates"]["sample"]
        self.assertEqual(g["status"], "regressed")
        self.assertEqual(g["notes"], ["feat: disabled (sample regressed)"])
        with open(flags, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertFalse(saved["feat"]["enabled"])
        self.assertTrue(saved["feat"]["reason"].startswith("sample re-run regressed: not reproducible"))
        self.assertTrue(saved["other"]["enabled"])

    def test_passed_false_result_regresses(self):
        gate = _gate("sample", lambda rng, config: {"passed": False})
        summary = nightly.run_nightly([(gate, {})])
        self.assertEqual(summary["gates"]["sample"]["status"], "regressed")
        self.assertTrue(summary["regressed"])

    def test_unconfirmed_gate_is_skipped(self):
        gate = _gate("G-99", lambda rng, config: {"passed": False})
        flags = self.write("flags.json", {"f": {"gate": "G-99", "enabled": True, "reason": ""}})
        code, out, _ = self.run_main(["--flags", flags], gates=[(gate, {})],
                                     preregistration_root=self.tmp.name)
        self.assertEqual(code, 0)
        g = json.loads(out)["gates"]["G-99"]
        self.assertEqual(g["status"], "skipped")
        self.assertIn("G-99", g["detail"])
        with open(flags, encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["f"]["enabled"])

    def test_passing_rerun_never_enables_disabled_flag(self):
        flags = self.write("flags.json", {"feat": {"gate": "sample", "enabled": False, "reason": "old"}})
        code, out, _ = self.run_main(["--flags", flags], gates=[(sample.run, {})])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["gates"]["sample"]["notes"],
                         ["feat: sample re-run passed; enabling is the operator's act"])
        with open(flags, encoding="utf-8") as fh:
            self.assertFalse(json.load(fh)["feat"]["enabled"])

    def test_bad_input_exits_2(self):
        bad = self.path("bad.json")
        with open(bad, "w") as fh:
            fh.write("{not json")
        self.assertEqual(self.run_main(["--flags", bad])[0], 2)
        self.assertEqual(self.run_main(["--previous", bad])[0], 2)
        self.assertEqual(self.run_main(["--flags", self.path("missing.json")])[0], 2)
        wrong = self.write("wrong.json", {"f": {"gate": "sample", "enabled": "yes"}})
        self.assertEqual(self.run_main(["--flags", wrong])[0], 2)
        self.assertEqual(self.run_main(["--bogus"])[0], 2)


if __name__ == "__main__":
    unittest.main()

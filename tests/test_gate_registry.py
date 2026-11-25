"""Schema tests for the gate registry (X-01)."""

import tempfile
import unittest
from pathlib import Path

from experiments.gates.registry import (
    DEFAULT_PATH,
    Gate,
    RegistryError,
    load_registry,
)

GOOD = """
[[gate]]
id = "G-01"
title = "First"
status = "pending"
result_doc = "experiments/results/G-01.md"
flags_unlocked = []
"""


class GateRegistryTest(unittest.TestCase):
    def _load(self, text, root=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.toml"
            path.write_text(text, encoding="utf-8")
            return load_registry(path, root=Path(root or tmp))

    def _rejects(self, text, *needles, root=None):
        with self.assertRaises(RegistryError) as ctx:
            self._load(text, root=root)
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))

    def test_shipped_registry_has_eleven_pending_gates(self):
        gates = load_registry(DEFAULT_PATH)
        self.assertEqual([g.id for g in gates], [f"G-{i:02d}" for i in range(1, 12)])
        self.assertTrue(all(isinstance(g, Gate) for g in gates))
        self.assertTrue(all(g.status == "pending" for g in gates))
        for g in gates:
            self.assertEqual(g.result_doc, f"experiments/results/{g.id}.md")
            self.assertEqual(g.flags_unlocked, ())

    def test_minimal_good_registry_loads(self):
        (gate,) = self._load(GOOD)
        self.assertIsNone(gate.threshold)

    def test_string_threshold_accepted(self):
        (gate,) = self._load(GOOD + 'threshold = "kappa >= 0.6"\n')
        self.assertEqual(gate.threshold, "kappa >= 0.6")

    def test_bad_status(self):
        self._rejects(GOOD.replace('"pending"', '"done"'), "G-01", "status")

    def test_bad_threshold_type(self):
        self._rejects(GOOD + "threshold = 0.6\n", "G-01", "threshold")

    def test_bad_result_doc(self):
        self._rejects(GOOD.replace("G-01.md", "G-02.md"), "G-01", "result_doc")

    def test_passed_requires_result_doc_file(self):
        self._rejects(GOOD.replace('"pending"', '"passed"'), "G-01", "result_doc")

    def test_passed_with_result_doc_file_loads(self):
        with tempfile.TemporaryDirectory() as root:
            doc = Path(root) / "experiments/results/G-01.md"
            doc.parent.mkdir(parents=True)
            doc.write_text("result\n", encoding="utf-8")
            (gate,) = self._load(GOOD.replace('"pending"', '"passed"'), root=root)
            self.assertEqual(gate.status, "passed")

    def test_duplicate_id(self):
        self._rejects(GOOD + GOOD, "G-01", "id")

    def test_bad_id_pattern(self):
        self._rejects(GOOD.replace('id = "G-01"', 'id = "G-1"'), "G-1", "id")

    def test_bad_flag_name(self):
        self._rejects(GOOD.replace("[]", '["Bad-Flag"]'), "G-01", "flags_unlocked")

    def test_flags_not_list(self):
        self._rejects(GOOD.replace("[]", '"x"'), "G-01", "flags_unlocked")

    def test_missing_title(self):
        self._rejects(GOOD.replace('title = "First"\n', ""), "G-01", "title")

    def test_unknown_field(self):
        self._rejects(GOOD + 'owner = "x"\n', "G-01", "owner")

    def test_no_gates(self):
        self._rejects("", "gate")


if __name__ == "__main__":
    unittest.main()

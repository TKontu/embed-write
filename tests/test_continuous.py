import unittest

from experiments.continuous import FlagRegistry, rerun_required


def _desc(model="m1", inventory="i1", method="cosine"):
    return {"modelVersion": model, "inventoryVersion": inventory, "method": method}


class RerunRequiredTest(unittest.TestCase):
    def test_no_change(self):
        self.assertEqual(rerun_required(_desc(), _desc()), [])

    def test_each_change_reported_in_order(self):
        self.assertEqual(rerun_required(_desc(), _desc(model="m2")), ["modelVersion"])
        self.assertEqual(
            rerun_required(_desc(), _desc(model="m2", inventory="i2", method="bm25")),
            ["modelVersion", "inventoryVersion", "method"],
        )

    def test_missing_key_counts_as_change(self):
        self.assertEqual(rerun_required({}, _desc()), ["modelVersion", "inventoryVersion", "method"])

    def test_unrelated_keys_ignored(self):
        cur = dict(_desc(), runId="x")
        self.assertEqual(rerun_required(_desc(), cur), [])


def _registry():
    return FlagRegistry.from_dict({
        "suggest": {"gate": "G-02", "enabled": True, "reason": "G-02 passed"},
        "suggest_v2": {"gate": "G-02", "enabled": False, "reason": "awaiting gate"},
        "cluster": {"gate": "G-05", "enabled": True, "reason": "G-05 passed"},
    })


class FlagRegistryTest(unittest.TestCase):
    def test_simulated_regression_disables_flag(self):
        reg = _registry()
        notes = reg.apply_rerun("G-02", passed=False, reason="modelVersion changed; recall fell")
        data = reg.to_dict()
        self.assertFalse(data["suggest"]["enabled"])
        self.assertIn("recall fell", data["suggest"]["reason"])
        self.assertFalse(data["suggest_v2"]["enabled"])
        self.assertTrue(any("suggest" in n for n in notes))

    def test_pass_never_enables(self):
        reg = _registry()
        notes = reg.apply_rerun("G-02", passed=True, reason="re-run passed")
        data = reg.to_dict()
        self.assertFalse(data["suggest_v2"]["enabled"])
        self.assertEqual(data["suggest_v2"]["reason"], "awaiting gate")
        self.assertTrue(data["suggest"]["enabled"])
        self.assertTrue(any("operator" in n and "suggest_v2" in n for n in notes))

    def test_unrelated_gate_untouched(self):
        reg = _registry()
        reg.apply_rerun("G-02", passed=False, reason="regressed")
        self.assertEqual(reg.to_dict()["cluster"], {"gate": "G-05", "enabled": True, "reason": "G-05 passed"})

    def test_round_trip_and_no_aliasing(self):
        src = {"f": {"gate": "G-01", "enabled": True, "reason": "r"}}
        reg = FlagRegistry.from_dict(src)
        reg.apply_rerun("G-01", passed=False, reason="x")
        self.assertTrue(src["f"]["enabled"])
        self.assertEqual(FlagRegistry.from_dict(reg.to_dict()).to_dict(), reg.to_dict())

    def test_invalid_entry_rejected(self):
        with self.assertRaises(ValueError):
            FlagRegistry.from_dict({"f": {"gate": "G-01", "enabled": "yes", "reason": ""}})
        with self.assertRaises(ValueError):
            FlagRegistry.from_dict({"f": {"enabled": True, "reason": ""}})

    def test_no_enable_api(self):
        self.assertFalse(any(name.startswith("enable") for name in dir(FlagRegistry)))


if __name__ == "__main__":
    unittest.main()

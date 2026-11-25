import dataclasses
import json
import re
import unittest

import service.verify_panel as panel_module
from service.verify_panel import AXIS_ORDER, AxisEntry, VerificationPanel, build_panel

ORIGINAL = "The rig weighs 5 kg and costs 1,200 [docs](https://ex.org/a) [@smith2020]."


class PanelShapeTest(unittest.TestCase):
    def test_six_entries_in_architecture_order(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        self.assertEqual(tuple(entry.axis for entry in panel.axes), AXIS_ORDER)
        self.assertEqual(
            AXIS_ORDER,
            ("Move preserved", "Meaning preserved", "Support preserved",
             "Register fit", "Grammar", "Length delta"),
        )

    def test_entries_are_frozen_dataclasses_with_to_dict(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        for entry in panel.axes:
            self.assertTrue(dataclasses.is_dataclass(entry))
            self.assertIsInstance(entry, AxisEntry)
            self.assertIsInstance(entry.to_dict(), dict)
            with self.assertRaises(dataclasses.FrozenInstanceError):
                entry.status = "changed"

    def test_panel_to_dict_is_json_serialisable(self):
        panel = build_panel(ORIGINAL, "The rig weighs 6 kg and costs 1,200.")
        text = json.dumps(panel.to_dict(), sort_keys=True)
        reloaded = json.loads(text)
        self.assertEqual([a["axis"] for a in reloaded["axes"]], list(AXIS_ORDER))
        self.assertEqual(reloaded["methods"], [panel_module.METHODS_DOC])

    def test_no_ranking_or_combining_attributes(self):
        forbidden = re.compile(r"score|total|overall|rank|mean|aggregate", re.I)
        panel = build_panel(ORIGINAL, ORIGINAL)
        for obj in (panel, *panel.axes):
            for name in dir(obj):
                if name.startswith("__"):
                    continue
                self.assertIsNone(forbidden.search(name), f"{type(obj).__name__}.{name}")
            for key in obj.to_dict():
                self.assertIsNone(forbidden.search(key), key)


class SupportAxisTest(unittest.TestCase):
    def test_altered_number_reports_missing_and_added_tokens(self):
        panel = build_panel("It weighs 5 kg.", "It weighs 6 kg.")
        entry = panel.entry("Support preserved")
        self.assertEqual(entry.status, "ok")
        self.assertIs(entry.value["preserved"], False)
        self.assertEqual(entry.value["missing"], {"num:5 kg": 1})
        self.assertEqual(entry.value["added"], {"num:6 kg": 1})
        self.assertEqual(entry.confidence, "deterministic-literal")

    def test_identical_text_preserves_support_and_zero_length_delta(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        support = panel.entry("Support preserved")
        self.assertIs(support.value["preserved"], True)
        self.assertEqual((support.value["missing"], support.value["added"]), ({}, {}))
        length = panel.entry("Length delta")
        self.assertEqual(length.status, "ok")
        self.assertEqual(
            (length.value["word_delta"], length.value["char_delta"]), (0, 0))
        self.assertEqual((length.value["word_ratio"], length.value["char_ratio"]),
                         (1.0, 1.0))
        self.assertEqual(length.confidence, "deterministic")

    def test_support_entry_records_the_still_entailed_residual(self):
        entry = build_panel("5 kg", "5 kg").entry("Support preserved")
        self.assertIn("still entailed", entry.note)


class UnavailableAxisTest(unittest.TestCase):
    def test_unimplemented_axes_are_present_but_unavailable(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        unavailable = [e.axis for e in panel.axes if e.status == "not_available"]
        self.assertEqual(unavailable,
                         ["Move preserved", "Meaning preserved", "Register fit", "Grammar"])
        for entry in panel.axes:
            if entry.axis in unavailable:
                self.assertIsNone(entry.value)
                self.assertIsNone(entry.confidence)

    def test_unknown_axis_lookup_fails_loudly(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        with self.assertRaises(KeyError):
            panel.entry("Aggregate quality")


class MethodLinkTest(unittest.TestCase):
    def test_every_entry_has_a_method_link(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        for entry in panel.axes:
            self.assertEqual(entry.method_link,
                             "docs/architecture.md#59-proposals-and-verification")

    def test_panel_lists_the_llm_not_final_judge_method_doc(self):
        panel = build_panel(ORIGINAL, ORIGINAL)
        self.assertIn("docs/methods/llm-not-final-judge.md", panel.methods)

    def test_panel_is_reusable_and_inputs_do_not_leak_into_values(self):
        panel = build_panel("one two", "one two three")
        self.assertIsInstance(panel, VerificationPanel)
        self.assertEqual(tuple(entry.axis for entry in panel.axes), AXIS_ORDER)
        self.assertNotIn("one two", json.dumps(panel.to_dict()))


if __name__ == "__main__":
    unittest.main()

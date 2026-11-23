"""SF-01..SF-03: Signal type, signal-kind registry, naming lint (I4, I8)."""

import dataclasses
import unittest

from analysis import signals
from analysis.signals import (
    BANNED_WORDS,
    Signal,
    SignalKind,
    get_kind,
    lint_display_name,
    register_kind,
    registered_kinds,
)


def make(**overrides):
    fields = dict(
        node_id="n1",
        level="sentence",
        kind="move",
        value="background",
        confidence=0.7,
        method_ref="move-classifier@v0",
        layer="provisional",
        computed_at="2026-11-23T00:00:00Z",
    )
    fields.update(overrides)
    return Signal(**fields)


class SignalTypeTest(unittest.TestCase):
    def test_valid_signal(self):
        s = make()
        self.assertEqual(s.confidence, 0.7)
        self.assertEqual(s.layer, "provisional")
        self.assertEqual(make(layer="confirmed").layer, "confirmed")

    def test_fields(self):
        self.assertEqual(
            [f.name for f in dataclasses.fields(Signal)],
            ["node_id", "level", "kind", "value", "confidence",
             "method_ref", "layer", "computed_at"],
        )

    def test_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            make().confidence = 0.1

    def test_required_fields_missing_raise_type_error(self):
        base = dict(node_id="n1", level="sentence", kind="move", value=1,
                    confidence=0.5, method_ref="m", layer="confirmed",
                    computed_at="t")
        for name in ("confidence", "method_ref", "layer"):
            kwargs = {k: v for k, v in base.items() if k != name}
            with self.subTest(missing=name), self.assertRaises(TypeError):
                Signal(**kwargs)

    def test_confidence_bounds(self):
        make(confidence=0.0)
        make(confidence=1.0)
        for bad in (-0.01, 1.01, float("nan")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make(confidence=bad)

    def test_confidence_must_be_number(self):
        for bad in (None, "0.5", True):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                make(confidence=bad)

    def test_layer(self):
        for bad in ("fast", "", None, "Confirmed"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make(layer=bad)

    def test_kind_must_be_registered(self):
        with self.assertRaises(ValueError):
            make(kind="no-such-kind")

    def test_empty_method_ref(self):
        for bad in ("", "   ", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make(method_ref=bad)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self._saved = dict(signals._REGISTRY)

    def tearDown(self):
        signals._REGISTRY.clear()
        signals._REGISTRY.update(self._saved)

    def test_prepopulated_from_architecture_5_6(self):
        expected = {
            "move": ("Move", ("G-01", "G-04")),
            "sequence_fit": ("Sequence fit", ("G-05",)),
            "register_fit": ("Register fit", ("G-06",)),
            "support": ("Support", ("G-07",)),
            "redundancy": ("Redundancy", ("G-04",)),
            "topic": ("Topic", ("G-11",)),
        }
        kinds = {k.name: k for k in registered_kinds()}
        self.assertEqual(set(kinds), set(expected))
        for name, (display, gate) in expected.items():
            k = get_kind(name)
            self.assertEqual(k.display_name, display)
            self.assertEqual(k.gate, gate)
            self.assertTrue(k.definition.strip())
            self.assertTrue(k.known_limits.strip())

    def test_every_registered_kind_passes_lint(self):
        for k in registered_kinds():
            with self.subTest(kind=k.name):
                lint_display_name(k.display_name)

    def test_register_and_duplicate(self):
        k = SignalKind("x_kind", ("G-99",), "X", "def", "limits")
        register_kind(k)
        self.assertIs(get_kind("x_kind"), k)
        make(kind="x_kind")
        with self.assertRaises(ValueError):
            register_kind(SignalKind("x_kind", ("G-99",), "Y", "d", "l"))

    def test_register_runs_lint(self):
        with self.assertRaises(ValueError):
            register_kind(SignalKind("bad", ("G-1",), "Prose Quality", "d", "l"))
        with self.assertRaises(KeyError):
            get_kind("bad")

    def test_register_requires_declarations(self):
        for kw in ({"gate": ()}, {"definition": ""}, {"known_limits": " "}):
            fields = dict(name="y", gate=("G-1",), display_name="Y",
                          definition="d", known_limits="l")
            fields.update(kw)
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                register_kind(SignalKind(**fields))

    def test_get_unknown_kind(self):
        with self.assertRaises(KeyError):
            get_kind("nope")


class NamingLintTest(unittest.TestCase):
    def test_banned_words(self):
        self.assertEqual(set(BANNED_WORDS),
                         {"quality", "score", "correct", "coherence"})
        for word in BANNED_WORDS:
            for variant in (word, word.upper(), f"Some {word.title()} thing"):
                with self.subTest(v=variant), self.assertRaises(ValueError):
                    lint_display_name(variant)

    def test_substrings_case_insensitive(self):
        for bad in ("Scored", "incorrect", "INCOHERENCE", "HighQualityness"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as cm:
                lint_display_name(bad)
            self.assertIn(bad, str(cm.exception))

    def test_clean_name_returns_name(self):
        self.assertEqual(lint_display_name("Register fit"), "Register fit")


if __name__ == "__main__":
    unittest.main()

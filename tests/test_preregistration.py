import json
from pathlib import Path
import tempfile
import unittest

from experiments.preregistration import PreregistrationError, load, require_confirmed


def fixture_record():
    # Synthetic test fixture only; never an expert confirmation of a real gate.
    return {"gate": "G-test", "threshold": "synthetic score >= 1", "metric": "score",
            "confirmed_by": "synthetic-test-fixture", "confirmed_at": "2026-01-01T00:00:00Z"}


class PreregistrationTest(unittest.TestCase):
    def test_valid_record_round_trips_with_optional_commit(self):
        with tempfile.TemporaryDirectory() as root:
            record = fixture_record()
            record["recorded_commit"] = "a" * 40
            (Path(root) / "G-test.json").write_text(json.dumps(record), encoding="utf-8")
            for reader in (load, require_confirmed):
                self.assertEqual(reader("G-test", root=root), record)

    def test_missing_record(self):
        with tempfile.TemporaryDirectory() as root:
            for reader in (load, require_confirmed):
                with self.assertRaises(PreregistrationError):
                    reader("G-test", root=root)

    def test_rejects_malformed_and_unconfirmed_records(self):
        invalid = ["{", "[]", "null", "42"]
        for field in fixture_record():
            record = fixture_record()
            del record[field]
            invalid.append(json.dumps(record))
            for value in ("", "  ", None, 42, []):
                invalid.append(json.dumps({**fixture_record(), field: value}))
        for timestamp in ("yesterday", "2026-01-01", "2026-01-01T00:00:00",
                          "2026-01-01T00:00:00+01:00", "2026-02-30T00:00:00Z"):
            invalid.append(json.dumps({**fixture_record(), "confirmed_at": timestamp}))
        invalid.append(json.dumps({**fixture_record(), "gate": "G-other"}))
        invalid.append(json.dumps({**fixture_record(), "recorded_commit": 42}))
        with tempfile.TemporaryDirectory() as root:
            for content in invalid:
                with self.subTest(content=content):
                    (Path(root) / "G-test.json").write_text(content, encoding="utf-8")
                    for reader in (load, require_confirmed):
                        with self.assertRaises(PreregistrationError):
                            reader("G-test", root=root)

    def test_rejects_non_utf8_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "G-test.json").write_bytes(b"\xff")
            for gate in ("G-test", "../G-test", "/G-test", "", None):
                with self.subTest(gate=gate), self.assertRaises(PreregistrationError):
                    load(gate, root=root)

    def test_accepts_explicit_utc_offset(self):
        with tempfile.TemporaryDirectory() as root:
            record = {**fixture_record(), "confirmed_at": "2026-01-01T00:00:00+00:00"}
            (Path(root) / "G-test.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(load("G-test", root=root), record)

"""Tests for service.source_items (SR-02). Fixtures are synthetic, LLM-built."""

import json
import os
import tempfile
import unittest

from service.source_items import (
    ALLOWED_TYPES, Provenance, SourceItem, SourceItemError, load_source_items, to_dict,
    validate_source_item, validate_source_items,
)


def valid(**over):
    obj = {
        "id": "m-001",
        "type": "measurement",
        "content": "Wall thickness 12 mm at grid line B3.",
        "units": ["mm"],
        "provenance": {
            "source": "site-visit-notes",
            "locator": "p. 4",
            "recorded_by": "inspector",
            "recorded_at": "2026-03-14",
        },
    }
    obj.update(over)
    return obj


def prov(**over):
    p = dict(valid()["provenance"])
    p.update(over)
    return p


class ValidItemTest(unittest.TestCase):
    def test_valid_item_validates_and_round_trips(self):
        item = validate_source_item(valid())
        self.assertEqual(item, SourceItem(
            "m-001", "measurement", "Wall thickness 12 mm at grid line B3.", ("mm",),
            Provenance("site-visit-notes", "p. 4", "inspector", "2026-03-14")))
        self.assertEqual(validate_source_item(to_dict(item)), item)
        self.assertEqual(to_dict(item), valid())

    def test_optional_provenance_fields(self):
        item = validate_source_item(valid(units=[], provenance={
            "source": "s", "recorded_by": "r"}))
        self.assertIsNone(item.provenance.locator)
        self.assertIsNone(item.provenance.recorded_at)
        self.assertEqual(validate_source_item(to_dict(item)), item)

    def test_datetime_recorded_at(self):
        for ts in ("2026-03-14T09:30:00", "2026-03-14T09:30:00+02:00", "2026-03-14T09:30Z"):
            validate_source_item(valid(provenance=prov(recorded_at=ts)))

    def test_all_allowed_types(self):
        for t in ALLOWED_TYPES:
            self.assertEqual(validate_source_item(valid(type=t)).type, t)


class FieldErrorTest(unittest.TestCase):
    def assertField(self, obj, field):
        with self.assertRaises(SourceItemError) as cm:
            validate_source_item(obj)
        self.assertTrue(str(cm.exception).startswith(field + ":"), str(cm.exception))

    def test_root_not_object(self):
        self.assertField(["x"], "<root>")

    def test_missing_fields(self):
        for key in ("id", "type", "content", "units", "provenance"):
            obj = valid()
            del obj[key]
            self.assertField(obj, key)
        for key in ("source", "recorded_by"):
            p = prov()
            del p[key]
            self.assertField(valid(provenance=p), f"provenance.{key}")

    def test_wrong_types(self):
        for key, bad in (("id", 5), ("id", True), ("id", ""), ("id", "-x"), ("id", "a b"),
                         ("type", True), ("content", ""), ("content", "  "),
                         ("content", False), ("units", "mm"), ("units", None),
                         ("provenance", "x")):
            self.assertField(valid(**{key: bad}), key)
        self.assertField(valid(units=["mm", True]), "units[1]")
        for key, bad in (("source", ""), ("source", True), ("locator", 3),
                         ("locator", False), ("recorded_by", None),
                         ("recorded_at", True), ("recorded_at", "14.3.2026"),
                         ("recorded_at", "2026-13-01")):
            self.assertField(valid(provenance=prov(**{key: bad})), f"provenance.{key}")

    def test_unknown_type(self):
        self.assertField(valid(type="rumour"), "type")

    def test_unit_alias_rejected_with_canonical_hint(self):
        with self.assertRaises(SourceItemError) as cm:
            validate_source_item(valid(units=["millimetre"]))
        self.assertIn("units[0]", str(cm.exception))
        self.assertIn('"mm"', str(cm.exception))
        self.assertField(valid(units=["furlong"]), "units[0]")

    def test_comment_keys_ignored_unknown_rejected(self):
        item = validate_source_item(valid(_note="hi", provenance=prov(_why="x")))
        self.assertEqual(item, validate_source_item(valid()))
        self.assertField(valid(extra=1), "extra")
        self.assertField(valid(provenance=prov(extra=1)), "provenance.extra")


class CollectionTest(unittest.TestCase):
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(SourceItemError) as cm:
            validate_source_items([valid(), valid(id="b"), valid()])
        self.assertTrue(str(cm.exception).startswith("[2].id:"), str(cm.exception))

    def test_index_prefixed_field_errors(self):
        with self.assertRaises(SourceItemError) as cm:
            validate_source_items([valid(), valid(id="b", type="x")])
        self.assertTrue(str(cm.exception).startswith("[1].type:"), str(cm.exception))

    def test_validate_many(self):
        items = validate_source_items([valid(), valid(id="b")])
        self.assertEqual([i.id for i in items], ["m-001", "b"])


class LoaderTest(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_loads_and_skips_blank_lines(self):
        path = self.write(json.dumps(valid()) + "\n\n   \n" + json.dumps(valid(id="b")) + "\n")
        self.assertEqual([i.id for i in load_source_items(path)], ["m-001", "b"])

    def test_bad_json_line_number(self):
        path = self.write(json.dumps(valid()) + "\n\n{not json\n")
        with self.assertRaises(SourceItemError) as cm:
            load_source_items(path)
        self.assertTrue(str(cm.exception).startswith("line 3:"), str(cm.exception))

    def test_invalid_item_line_number(self):
        path = self.write(json.dumps(valid()) + "\n" + json.dumps(valid(id="b", units=[1])))
        with self.assertRaises(SourceItemError) as cm:
            load_source_items(path)
        self.assertTrue(str(cm.exception).startswith("line 2: units[0]:"), str(cm.exception))

    def test_duplicate_line_number(self):
        path = self.write(json.dumps(valid()) + "\n" + json.dumps(valid()) + "\n")
        with self.assertRaises(SourceItemError) as cm:
            load_source_items(path)
        self.assertTrue(str(cm.exception).startswith("line 2: id:"), str(cm.exception))

    def test_missing_file(self):
        with self.assertRaises(SourceItemError):
            load_source_items("/nonexistent/items.jsonl")


if __name__ == "__main__":
    unittest.main()

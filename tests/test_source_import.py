"""Tests for service/source_import.py (todo-09 SR-03). Fixtures are synthetic, LLM-built."""

import os
import tempfile
import unittest

from service.source_import import (export_captions, export_notes, export_table, import_captions,
                                   import_notes, import_table, slug_id)
from service.source_items import Provenance, SourceItem, SourceItemError

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "source_import")


def fx(name):
    return os.path.join(FIX, name)


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)

    def write(self, name, text):
        path = os.path.join(self._d.name, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def path(self, name):
        return os.path.join(self._d.name, name)

    def assertErr(self, fn, *parts):
        with self.assertRaises(SourceItemError) as cm:
            fn()
        for part in parts:
            self.assertIn(part, str(cm.exception))


class TableTests(_Tmp):
    def test_csv_fixture(self):
        items = import_table(fx("table.csv"), recorded_by="tester")
        self.assertEqual([i.id for i in items], ["m-001", "t-002", "o-003"])
        self.assertEqual(items[0], SourceItem(
            "m-001", "measurement", "Beam deflection at midspan 4.2 mm", ("mm",),
            Provenance("table.csv", "sheet1!B2", "tester", "2026-03-01")))
        self.assertEqual(items[1].content, "Tensile test passed, 410 kPa")
        self.assertEqual(items[1].provenance.source, "lab-log.csv")
        self.assertEqual(items[2].units, ())
        self.assertIsNone(items[2].provenance.locator)

    def test_tsv_fixture_and_default_source(self):
        items = import_table(fx("table.tsv"), source="lab", recorded_by="t")
        self.assertEqual(items[0].units, ("°C", "%"))
        self.assertEqual(items[0].provenance.source, "lab")

    def test_round_trip(self):
        for name in ("table.csv", "table.tsv"):
            items = import_table(fx(name), recorded_by="t")
            out = self.path("out" + os.path.splitext(name)[1])
            export_table(items, out)
            self.assertEqual(import_table(out, recorded_by="t"), items)

    def test_explicit_delimiter(self):
        p = self.write("x.txt", "id|type|content\na|observation|hi\n")
        self.assertEqual(import_table(p, recorded_by="t", delimiter="|")[0].id, "a")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "delimiter")

    def test_missing_required_column(self):
        p = self.write("x.csv", "id,content\na,hi\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 0", "type")

    def test_unknown_column(self):
        p = self.write("x.csv", "id,type,content,colour\na,observation,hi,red\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 0", "colour")

    def test_bad_type(self):
        p = self.write("x.csv", "id,type,content\na,observation,hi\nb,gossip,x\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 2", "type")

    def test_non_canonical_unit(self):
        p = self.write("x.csv", "id,type,content,units\na,measurement,hi,millimetre\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 1", "units", '"mm"')

    def test_bad_recorded_at(self):
        p = self.write("x.csv", "id,type,content,recorded_at\na,observation,hi,yesterday\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 1", "recorded_at")

    def test_duplicate_id(self):
        p = self.write("x.csv", "id,type,content\na,observation,hi\na,observation,ho\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 2", "duplicate id")

    def test_wrong_cell_count(self):
        p = self.write("x.csv", "id,type,content\na,observation\n")
        self.assertErr(lambda: import_table(p, recorded_by="t"), "row 1", "cells")

    def test_spreadsheet_rejected(self):
        for ext in (".xlsx", ".ods"):
            p = self.write("x" + ext, "")
            self.assertErr(lambda: import_table(p, recorded_by="t"), "export", "CSV")


class NotesTests(_Tmp):
    def test_fixture(self):
        items = import_notes(fx("notes.txt"), recorded_by="t")
        self.assertEqual(items[0], SourceItem(
            "n-001", "observation",
            "Surface rust on the north flange.\nSecond line kept verbatim.", (),
            Provenance("notes.txt", "p. 3", "t", "2026-04-10")))
        self.assertEqual(items[1].units, ("mm", "m"))
        self.assertEqual(items[1].provenance.source, "field-notebook")

    def test_round_trip(self):
        items = import_notes(fx("notes.txt"), recorded_by="t")
        out = self.path("out.txt")
        export_notes(items, out)
        self.assertEqual(import_notes(out, recorded_by="t"), items)

    def test_missing_required_key(self):
        p = self.write("n.txt", "id: a\n\nbody\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "block 1", "line 1", "type")

    def test_bad_type(self):
        p = self.write("n.txt", "id: a\ntype: observation\n\nx\n---\nid: b\ntype: nope\n\ny\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "block 2", "line 7", "type")

    def test_non_canonical_unit(self):
        p = self.write("n.txt", "id: a\ntype: measurement\nunits: millimetre\n\nx\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "block 1", "units")

    def test_bad_recorded_at(self):
        p = self.write("n.txt", "id: a\ntype: observation\nrecorded_at: soon\n\nx\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "block 1", "recorded_at")

    def test_duplicate_id(self):
        p = self.write("n.txt", "id: a\ntype: observation\n\nx\n---\nid: a\ntype: observation\n\ny\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "block 2", "duplicate id")

    def test_bad_header_line(self):
        p = self.write("n.txt", "id: a\nnot a key line\n\nx\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "block 1", "line 2")
        p = self.write("n.txt", "id: a\ncolour: red\n\nx\n")
        self.assertErr(lambda: import_notes(p, recorded_by="t"), "line 2", "colour")

    def test_export_rejects_unrepresentable(self):
        prov = Provenance("s", None, "t", None)
        bad = SourceItem("a", "observation", "x\n---\ny", (), prov)
        self.assertErr(lambda: export_notes([bad], self.path("o.txt")), "---")


class CaptionTests(_Tmp):
    def test_fixture(self):
        items = import_captions(fx("captions.csv"), recorded_by="t")
        self.assertEqual(items[0], SourceItem(
            "img-0042", "photo_note", "Crack at the north support", (),
            Provenance("photos/IMG 0042.JPG", "frame 1", "t", "2026-05-01")))
        self.assertEqual(items[1].id, "custom-id")

    def test_round_trip(self):
        items = import_captions(fx("captions.csv"), recorded_by="t")
        out = self.path("o.csv")
        export_captions(items, out)
        self.assertEqual(import_captions(out, recorded_by="t"), items)

    def test_slug(self):
        self.assertEqual(slug_id("a/b/IMG 0042.JPG"), "img-0042")
        self.assertEqual(slug_id("__x__y.tar.png"), "x-y.tar")
        self.assertEqual(slug_id("Ä ö.jpg"), "a-o")
        with self.assertRaises(SourceItemError):
            slug_id("___.png")

    def test_slug_collision(self):
        p = self.write("c.csv", "image,caption\na/IMG_1.jpg,one\nb/img 1.png,two\n")
        self.assertErr(lambda: import_captions(p, recorded_by="t"), "row 2", "duplicate id")

    def test_missing_column(self):
        p = self.write("c.csv", "image,id\na.jpg,x\n")
        self.assertErr(lambda: import_captions(p, recorded_by="t"), "row 0", "caption")

    def test_bad_recorded_at(self):
        p = self.write("c.csv", "image,caption,recorded_at\na.jpg,x,never\n")
        self.assertErr(lambda: import_captions(p, recorded_by="t"), "row 1", "recorded_at")

    def test_export_rejects_other_types(self):
        item = SourceItem("a", "observation", "x", (), Provenance("s", None, "t", None))
        self.assertErr(lambda: export_captions([item], self.path("o.csv")), "photo_note")


if __name__ == "__main__":
    unittest.main()

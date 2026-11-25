"""CO-08: fixed, versioned train/dev/test split by document (synthetic fixtures, offline)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from experiments import corpus_split as cs
from experiments.splits import DocumentSplit


def rec(doc_id):
    return {
        "doc_id": doc_id,
        "genre": "inspection-report",
        "date": "2024-03-15",
        "author_role": "inspector",
        "language": "fi",
        "length": 100,
    }


IDS = [f"r-{i:03d}" for i in range(40)]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def meta(self, ids=IDS, name="meta.jsonl", extra=""):
        p = self.dir / name
        p.write_text("".join(json.dumps(rec(i)) + "\n" for i in ids) + extra, encoding="utf-8")
        return p


class BuildTests(Base):
    def test_deterministic_and_order_independent(self):
        a = cs.build_split(self.meta(IDS, "a.jsonl"), seed=3, dev=0.2, test=0.2)
        b = cs.build_split(self.meta(list(reversed(IDS)), "b.jsonl"), seed=3, dev=0.2, test=0.2)
        self.assertEqual(a, b)

    def test_seed_changes_assignment(self):
        m = self.meta()
        a = cs.build_split(m, seed=1, dev=0.2, test=0.2)
        b = cs.build_split(m, seed=2, dev=0.2, test=0.2)
        self.assertNotEqual(a["splits"], b["splits"])

    def test_disjoint_complete_sorted(self):
        m = cs.build_split(self.meta(), seed=0, dev=0.2, test=0.25)
        s = m["splits"]
        sets = [set(s[k]) for k in cs.SPLIT_NAMES]
        self.assertEqual(sum(len(x) for x in sets), len(IDS))
        self.assertEqual(set().union(*sets), set(IDS))
        for k in cs.SPLIT_NAMES:
            self.assertEqual(s[k], sorted(s[k]))
        self.assertEqual(len(s["test"]), 10)
        self.assertEqual(len(s["dev"]), 8)
        self.assertEqual(m["version"], cs.FORMAT_VERSION)
        self.assertEqual(m["seed"], 0)
        self.assertEqual(cs.verify_manifest(m), [])

    def test_fraction_validation(self):
        m = self.meta()
        for dev, test in [(0, 0.2), (0.2, 0), (-0.1, 0.2), (0.5, 0.5), (0.6, 0.5), (True, 0.2)]:
            with self.assertRaises(cs.SplitError, msg=(dev, test)):
                cs.build_split(m, seed=0, dev=dev, test=test)

    def test_too_few_documents(self):
        with self.assertRaises(cs.SplitError):
            cs.build_split(self.meta(["a", "b"]), seed=0, dev=0.3, test=0.3)
        # three documents can be split 1/1/1
        m = cs.build_split(self.meta(["a", "b", "c"]), seed=0, dev=0.3, test=0.3)
        self.assertEqual([len(m["splits"][k]) for k in cs.SPLIT_NAMES], [1, 1, 1])

    def test_invalid_metadata_refused(self):
        with self.assertRaises(cs.SplitError):
            cs.build_split(self.meta(extra='{"doc_id": "x"}\n'), seed=0, dev=0.2, test=0.2)

    def test_duplicate_doc_id_refused(self):
        with self.assertRaises(cs.SplitError):
            cs.build_split(self.meta(IDS + ["r-001"]), seed=0, dev=0.2, test=0.2)


class CheckTests(Base):
    def setUp(self):
        super().setUp()
        self.m = cs.build_split(self.meta(), seed=0, dev=0.2, test=0.2)

    def test_overlap(self):
        self.m["splits"]["dev"] = sorted(self.m["splits"]["dev"] + [self.m["splits"]["train"][0]])
        self.m["sha256"] = cs.splits_hash(self.m["splits"])
        errs = cs.verify_manifest(self.m)
        self.assertTrue(any("more than one split" in e for e in errs), errs)

    def test_hash_tamper(self):
        self.m["splits"]["train"] = self.m["splits"]["train"][1:]
        self.assertTrue(any("sha256" in e for e in cs.verify_manifest(self.m)))

    def test_bad_version(self):
        self.m["version"] = 99
        self.assertTrue(any("version" in e for e in cs.verify_manifest(self.m)))

    def test_schema(self):
        self.assertTrue(cs.verify_manifest([]))
        del self.m["seed"]
        self.assertTrue(any("seed" in e for e in cs.verify_manifest(self.m)))

    def test_missing_and_unknown_vs_metadata(self):
        self.assertEqual(cs.verify_manifest(self.m, self.meta()), [])
        errs = cs.verify_manifest(self.m, self.meta(IDS + ["new-1"], "more.jsonl"))
        self.assertTrue(any("new-1" in e and "not in any split" in e for e in errs), errs)
        errs = cs.verify_manifest(self.m, self.meta(IDS[1:], "fewer.jsonl"))
        self.assertTrue(any("r-000" in e and "unknown" in e for e in errs), errs)


class IoAndAdapterTests(Base):
    def test_write_refuses_overwrite(self):
        m = cs.build_split(self.meta(), seed=0, dev=0.2, test=0.2)
        out = self.dir / "split.json"
        cs.write_manifest(m, out)
        with self.assertRaises(FileExistsError):
            cs.write_manifest(m, out)
        cs.write_manifest(m, out, force=True)
        self.assertEqual(cs.load_manifest(out), m)

    def test_load_rejects_invalid(self):
        p = self.dir / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(cs.SplitError):
            cs.load_manifest(p)

    def test_to_document_split(self):
        m = cs.build_split(self.meta(), seed=0, dev=0.2, test=0.2)
        t = cs.to_document_split(m)
        self.assertIsInstance(t, DocumentSplit)
        self.assertEqual(t.train_ids, frozenset(m["splits"]["train"]))
        self.assertEqual(t.test_ids, frozenset(m["splits"]["test"]))
        d = cs.to_document_split(m, eval_split="dev")
        self.assertEqual(d.test_ids, frozenset(m["splits"]["dev"]))
        with self.assertRaises(ValueError):
            cs.to_document_split(m, eval_split="train")


class CliTests(Base):
    def run_cli(self, *argv):
        err = io.StringIO()
        with redirect_stderr(err):
            code = cs.main([str(a) for a in argv])
        return code, err.getvalue()

    def test_build_and_check(self):
        meta, out = self.meta(), self.dir / "s.json"
        args = ("build", meta, out, "--seed", 1, "--dev", 0.2, "--test", 0.2)
        self.assertEqual(self.run_cli(*args)[0], 0)
        code, err = self.run_cli(*args)
        self.assertEqual(code, 1)
        self.assertIn("exists", err)
        self.assertEqual(self.run_cli(*args, "--force")[0], 0)
        self.assertEqual(self.run_cli("check", out)[0], 0)
        self.assertEqual(self.run_cli("check", out, "--metadata", meta)[0], 0)
        other = self.meta(IDS + ["zz"], "o.jsonl")
        code, err = self.run_cli("check", out, "--metadata", other)
        self.assertEqual(code, 1)
        self.assertIn("zz", err)

    def test_build_invalid_metadata_exit_1(self):
        meta = self.meta(extra="not json\n")
        code, err = self.run_cli("build", meta, self.dir / "s.json", "--seed", 0, "--dev", 0.2, "--test", 0.2)
        self.assertEqual(code, 1)
        self.assertIn(":41:", err)
        self.assertFalse((self.dir / "s.json").exists())


if __name__ == "__main__":
    unittest.main()

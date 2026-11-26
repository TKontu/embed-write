"""PT-01 tests; all labels are LLM-built synthetic fixtures."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from analysis.label_store import CandidateLabelStore
from analysis.training_set import build_training_set, load_document_map, main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slow(node, label, ts=1):
    return {"node_id": node, "label": label, "source": "slow_layer",
            "model_version": "m1", "timestamp": ts}


def corpus(n_docs=40, per_doc=3):
    cands, docs = [], {}
    for d in range(n_docs):
        for s in range(per_doc):
            node = f"d{d}-s{s}"
            docs[node] = f"doc{d}"
            cands.append(slow(node, ["claim", "method", "result"][s % 3]))
    return cands, docs


class TrainingSetTests(unittest.TestCase):
    def test_expert_overturns_slow_layer(self):
        cands = [slow("n1", "claim", ts=5),
                 {"node_id": "n1", "label": "method", "source": "expert", "timestamp": 1}]
        out = build_training_set(cands, {"n1": "docA"}, held_out_fraction=0.0)
        self.assertEqual(out["train"], [("n1", "docA", "method", "expert")])

    def test_documents_never_in_both_splits(self):
        cands, docs = corpus()
        out = build_training_set(cands, docs)
        train_docs = {r[1] for r in out["train"]}
        held_docs = {r[1] for r in out["held_out"]}
        self.assertTrue(train_docs and held_docs)
        self.assertFalse(train_docs & held_docs)
        self.assertEqual(len(out["train"]) + len(out["held_out"]), len(cands))

    def test_split_independent_of_input_order(self):
        cands, docs = corpus()
        a = build_training_set(cands, docs, seed=7)
        b = build_training_set(list(reversed(cands)), dict(reversed(list(docs.items()))), seed=7)
        self.assertEqual(a, b)
        c = build_training_set(cands, docs, seed=8)
        self.assertNotEqual({r[1] for r in a["held_out"]}, {r[1] for r in c["held_out"]})

    def test_missing_document_mapping_raises(self):
        with self.assertRaisesRegex(ValueError, "orphan"):
            build_training_set([slow("orphan", "claim")], {})

    def test_counts_per_split(self):
        cands, docs = corpus()
        out = build_training_set(cands, docs)
        for split in ("train", "held_out"):
            rows = out[split]
            counts = out["counts"][split]
            self.assertEqual(counts["examples"], len(rows))
            self.assertEqual(counts["documents"], len({r[1] for r in rows}))
            self.assertEqual(sum(counts["labels"].values()), len(rows))

    def test_bad_fraction_and_conflicting_map(self):
        with self.assertRaises(ValueError):
            build_training_set([], {}, held_out_fraction=1.5)
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "d.jsonl")
            with open(p, "w") as fh:
                fh.write('{"node_id":"n","document_id":"a"}\n{"node_id":"n","document_id":"b"}\n')
            with self.assertRaisesRegex(ValueError, "two documents"):
                load_document_map(p)

    def test_cli_round_trip(self):
        cands, docs = corpus(n_docs=10, per_doc=2)
        with tempfile.TemporaryDirectory() as tmp:
            labels = os.path.join(tmp, "labels.jsonl")
            store = CandidateLabelStore(labels)
            for c in cands:
                store.append(c["node_id"], c["label"], c["model_version"], c["timestamp"])
            documents = os.path.join(tmp, "docs.jsonl")
            with open(documents, "w", encoding="utf-8") as fh:
                for node, doc in docs.items():
                    fh.write(json.dumps({"node_id": node, "document_id": doc}) + "\n")
            proc = subprocess.run(
                [sys.executable, "-m", "analysis.training_set", "--labels", labels,
                 "--documents", documents, "--seed", "3", "--held-out", "0.3"],
                cwd=ROOT, capture_output=True, text=True, check=True)
            got = json.loads(proc.stdout)
            expected = build_training_set(store.iter_candidates(), docs,
                                          held_out_fraction=0.3, seed=3)["counts"]
            self.assertEqual(got, expected)
            self.assertEqual(got["train"]["examples"] + got["held_out"]["examples"], 20)
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(main(["--labels", labels, "--documents", documents,
                                       "--seed", "3", "--held-out", "0.3"]), 0)
            self.assertEqual(json.loads(buf.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()

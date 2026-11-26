"""PT-02 tests; all vectors and labels are LLM-built synthetic, linearly separable fixtures."""

import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

from analysis.classifier_head import evaluate, load_model, make_model
from analysis.label_store import CandidateLabelStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = ["claim", "method", "result"]
DIM = 6


def vector_for(label, rng):
    v = [rng.gauss(0.0, 0.3) for _ in range(DIM)]
    v[LABELS.index(label)] += 3.0
    return v


def synthetic(n_docs=20, per_doc=6, seed=1):
    rng = random.Random(seed)
    rows, vectors = [], {}
    for d in range(n_docs):
        for s in range(per_doc):
            node, label = f"d{d}-s{s}", LABELS[s % 3]
            rows.append((node, f"doc{d}", label, "slow_layer"))
            vectors[node] = vector_for(label, rng)
    train = [r for r in rows if int(r[1][3:]) < n_docs * 3 // 4]
    held = [r for r in rows if int(r[1][3:]) >= n_docs * 3 // 4]
    return train, held, vectors


FAST = {"epochs": 30}


class ClassifierHeadTests(unittest.TestCase):
    def test_both_models_separate_held_out(self):
        train, held, vectors = synthetic()
        for name in ("logreg", "mlp"):
            model = make_model(name, seed=0, **FAST).fit(train, vectors)
            report = evaluate(model, held, vectors)
            self.assertGreaterEqual(report["macro_f1"], 0.9, name)
            self.assertEqual(report["examples"], len(held))
            self.assertEqual(report["documents"], 5)

    def test_deterministic_for_seed(self):
        train, held, vectors = synthetic()
        for name in ("logreg", "mlp"):
            a = make_model(name, seed=4, **FAST).fit(train, vectors)
            b = make_model(name, seed=4, **FAST).fit(train, vectors)
            self.assertEqual(a.params, b.params)
            self.assertEqual(a.predict_proba(held, vectors), b.predict_proba(held, vectors))

    def test_unseen_label_scores_zero(self):
        train, held, vectors = synthetic()
        vectors["extra"] = [0.0] * DIM
        held = held + [("extra", "doc99", "background", "expert")]
        model = make_model("logreg", **FAST).fit(train, vectors)
        report = evaluate(model, held, vectors)
        row = report["per_label"]["background"]
        self.assertEqual((row["f1"], row["support"], row["seen_in_train"]), (0.0, 1, False))
        self.assertEqual(len(report["per_label"]), 4)

    def test_missing_or_missized_vector_names_node(self):
        train, _, vectors = synthetic()
        del vectors[train[3][0]]
        with self.assertRaisesRegex(ValueError, train[3][0]):
            make_model("logreg", **FAST).fit(train, vectors)
        train, _, vectors = synthetic()
        vectors[train[2][0]] = [1.0] * (DIM + 1)
        with self.assertRaisesRegex(ValueError, train[2][0]):
            make_model("mlp", **FAST).fit(train, vectors)
        model = make_model("logreg", **FAST).fit(*synthetic()[::2])
        with self.assertRaisesRegex(ValueError, "odd"):
            model.predict([("odd", "d", "claim", "x")], {"odd": [1.0]})
        with self.assertRaisesRegex(ValueError, "odd"):
            model.predict([("odd", "d", "claim", "x")], lambda n: None)

    def test_save_load_round_trip(self):
        train, held, vectors = synthetic()
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("logreg", "mlp"):
                model = make_model(name, seed=2, **FAST).fit(train, vectors)
                path = os.path.join(tmp, f"{name}.json")
                model.save(path)
                loaded = load_model(path)
                self.assertEqual(loaded.predict_proba(held, vectors),
                                 model.predict_proba(held, vectors))

    def test_unknown_model(self):
        with self.assertRaises(ValueError):
            make_model("forest")

    def test_cli_end_to_end(self):
        rng = random.Random(5)
        with tempfile.TemporaryDirectory() as tmp:
            labels = os.path.join(tmp, "labels.jsonl")
            docs = os.path.join(tmp, "docs.jsonl")
            vecs = os.path.join(tmp, "vectors.jsonl")
            out = os.path.join(tmp, "model.json")
            store = CandidateLabelStore(labels)
            with open(docs, "w") as dfh, open(vecs, "w") as vfh:
                for d in range(20):
                    for s in range(3):
                        node, label = f"d{d}-s{s}", LABELS[s]
                        store.append(node, label, "m1", 1)
                        dfh.write(json.dumps({"node_id": node, "document_id": f"doc{d}"}) + "\n")
                        vfh.write(json.dumps({"node_id": node,
                                              "vector": vector_for(label, rng)}) + "\n")
                vfh.write(json.dumps({"node_id": "unlabelled", "vector": [0.0]}) + "\n")
            proc = subprocess.run(
                [sys.executable, "-m", "analysis.classifier_head", "--labels", labels,
                 "--documents", docs, "--vectors", vecs, "--model", "mlp", "--seed", "1",
                 "--held-out", "0.3", "--out", out],
                cwd=ROOT, capture_output=True, text=True, check=True)
            report = json.loads(proc.stdout)
            held = report["held_out"]
            self.assertIn("macro_f1", held)
            self.assertGreater(held["documents"], 0)
            self.assertEqual(sum(v["support"] for v in held["per_label"].values()),
                             held["examples"])
            self.assertEqual(report["train"]["documents"] + held["documents"], 20)
            self.assertEqual(load_model(out).kind, "mlp")


if __name__ == "__main__":
    unittest.main()

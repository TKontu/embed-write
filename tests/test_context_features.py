"""PT-03 context features tests. All data is LLM-built synthetic, generated in-test."""

import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

from analysis.context_features import ablate, augment, load_context, section_vocab
from analysis.label_store import CandidateLabelStore
from analysis.training_set import build_training_set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def neighbour_world(n_docs=24, seed=3, noise_context=False):
    """Sections of two sentences; only the second is labelled.

    Neighbour world: own vector is noise, label = sign of the previous sentence's first component.
    Noise world: label is in the own vector; neighbours and section types are random.
    """
    rng = random.Random(seed)
    context, vectors, labelled, docs = [], {}, [], {}
    for d in range(n_docs):
        for s in range(2):
            sec, doc = f"sec{d}-{s}", f"doc{d}"
            lead, follow = f"d{d}-{s}-0", f"d{d}-{s}-1"
            label = rng.choice(["pos", "neg"])
            sign = 1.0 if label == "pos" else -1.0
            if noise_context:
                vectors[lead] = [rng.gauss(0, 1), rng.gauss(0, 1)]
                vectors[follow] = [sign * 2 + rng.gauss(0, 0.2), rng.gauss(0, 0.2)]
                stype = rng.choice(["intro", "methods"])
            else:
                vectors[lead] = [sign * 2 + rng.gauss(0, 0.2), rng.gauss(0, 0.2)]
                vectors[follow] = [rng.gauss(0, 1), rng.gauss(0, 1)]
                stype = "body"
            for i, node in enumerate((lead, follow)):
                context.append({"node_id": node, "document_id": doc, "section_id": sec,
                                "section_type": stype, "index": i})
                docs[node] = doc
            labelled.append((follow, label))
    return context, vectors, labelled, docs



def split_for(labelled, docs, tmp, seed=0):
    store = CandidateLabelStore(os.path.join(tmp, "labels.jsonl"))
    for node, label in labelled:
        store.append(node, label, "m1", 1)
    return build_training_set(store.iter_candidates(), docs, held_out_fraction=0.3, seed=seed)


class ContextFeaturesTest(unittest.TestCase):
    def test_neighbours_stay_in_section_and_pad_with_zeros(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ctx.jsonl")
            write_jsonl(path, [
                {"node_id": "a", "document_id": "D", "section_id": "S1", "section_type": "x",
                 "index": 0},
                {"node_id": "b", "document_id": "D", "section_id": "S1", "section_type": "x",
                 "index": 1},
                {"node_id": "c", "document_id": "D", "section_id": "S2", "section_type": "y",
                 "index": 2},
                {"node_id": "z", "document_id": "E", "section_id": "S1", "section_type": "x",
                 "index": 2},
            ])
            ctx = load_context(path, {"b", "c"})
        self.assertEqual(set(ctx), {"b", "c"})
        self.assertEqual((ctx["b"]["prev"], ctx["b"]["next"]), ("a", None))
        self.assertEqual((ctx["c"]["prev"], ctx["c"]["next"]), (None, None))
        vecs = {"a": [1.0, 2.0], "b": [3.0, 4.0], "c": [5.0, 6.0], "z": [9.0, 9.0]}
        out = augment(vecs, ctx, True, False)
        self.assertEqual(out["b"], [3.0, 4.0, 1.0, 2.0, 0.0, 0.0])
        self.assertEqual(out["c"], [5.0, 6.0, 0.0, 0.0, 0.0, 0.0])

    def test_section_vocab_from_train_only(self):
        ctx = {"a": {"section_type": "intro", "prev": None, "next": None},
               "b": {"section_type": "results", "prev": None, "next": None}}
        train = [("a", "D1", "m", "expert")]
        vocab = section_vocab(train, ctx)
        self.assertEqual(vocab, ["intro"])
        out = augment({"a": [1.0], "b": [2.0]}, ctx, False, True, vocab)
        self.assertEqual(out["a"], [1.0, 1.0])
        self.assertEqual(out["b"], [2.0, 0.0])

    def _ablate(self, noise_context, seed=0):
        context, vectors, labelled, docs = neighbour_world(noise_context=noise_context)
        with tempfile.TemporaryDirectory() as tmp:
            split = split_for(labelled, docs, tmp)
            path = os.path.join(tmp, "ctx.jsonl")
            write_jsonl(path, context)
            wanted = {r[0] for r in split["train"] + split["held_out"]}
            ctx = load_context(path, wanted)
        return ablate(split, vectors, ctx, "logreg", seed)

    def test_context_kept_when_label_depends_on_neighbour(self):
        report = self._ablate(False)
        self.assertGreater(report["held_out"]["documents"], 0)
        self.assertGreater(report["macro_f1"]["context"], report["macro_f1"]["baseline"])
        self.assertGreater(report["macro_f1"]["context"], 0.9)
        self.assertEqual(report["verdict"], "keep")

    def test_context_dropped_when_noise(self):
        report = self._ablate(True)
        self.assertNotEqual(report["verdict"], "keep")
        self.assertLessEqual(report["delta"], 0.0)

    def test_deterministic(self):
        self.assertEqual(self._ablate(False, seed=4), self._ablate(False, seed=4))

    def test_cli_end_to_end(self):
        context, vectors, labelled, docs = neighbour_world()
        with tempfile.TemporaryDirectory() as tmp:
            labels = os.path.join(tmp, "labels.jsonl")
            store = CandidateLabelStore(labels)
            for node, label in labelled:
                store.append(node, label, "m1", 1)
            paths = {k: os.path.join(tmp, f"{k}.jsonl") for k in ("docs", "vecs", "ctx")}
            write_jsonl(paths["docs"], [{"node_id": n, "document_id": d} for n, d in docs.items()])
            write_jsonl(paths["vecs"], [{"node_id": n, "vector": v} for n, v in vectors.items()])
            write_jsonl(paths["ctx"], context)
            cmd = [sys.executable, "-m", "analysis.context_features", "--labels", labels,
                   "--documents", paths["docs"], "--vectors", paths["vecs"],
                   "--context", paths["ctx"], "--held-out", "0.3", "--no-section"]
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
            report = json.loads(proc.stdout)
        self.assertEqual(set(report["macro_f1"]), {"baseline", "context"})
        self.assertEqual(report["verdict"], "keep")
        self.assertFalse(report["use_section"])
        self.assertEqual(report["train"]["documents"] + report["held_out"]["documents"], 24)


if __name__ == "__main__":
    unittest.main()

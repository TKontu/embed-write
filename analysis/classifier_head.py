"""PT-02 move classifier head on sentence embeddings (pure stdlib).

Two models over per-sentence vectors (invariant I2: sentence-level vectors only):
- "logreg": multinomial logistic regression (softmax, L2, mini-batch gradient descent);
- "mlp": one hidden tanh layer feeding a softmax output.
Both are deterministic for a fixed seed (random.Random(seed) for init and batch order).

Rows come from analysis.training_set.build_training_set: (node_id, document_id, label, source).
evaluate() reports macro-F1 over every label seen in train or held-out, so a held-out label the
model never saw contributes F1 0.

Unwired by design: the production caller is the fast layer (PT-04 calibration / PT-05 ONNX).
Residual: training memory is O(examples x dim) plus O(dim x labels) weights; only labelled nodes'
vectors are loaded (load_vectors streams the JSONL). The 100k sentences x 768 dims bound is
untested and pure-Python training at that size will be slow.
"""

import argparse
import json
import math
import random
import sys

from analysis.label_store import CandidateLabelStore
from analysis.training_set import build_training_set, load_document_map


def _lookup(vectors, node_id):
    if callable(vectors):
        vector = vectors(node_id)
    else:
        vector = vectors.get(node_id)
    if vector is None:
        raise ValueError(f"node {node_id!r} has no vector")
    return [float(x) for x in vector]


def _matrix(rows, vectors, dim=None):
    xs = []
    for row in rows:
        vector = _lookup(vectors, row[0])
        if dim is None:
            dim = len(vector)
        if len(vector) != dim or dim == 0:
            raise ValueError(f"node {row[0]!r} vector has dimension {len(vector)}, expected {dim}")
        xs.append(vector)
    return xs, dim


def _softmax(z):
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return [v / s for v in e]


def _affine(w, b, x):
    return [bj + sum(wi * xi for wi, xi in zip(wj, x)) for wj, bj in zip(w, b)]


class _Model:
    kind = None

    def __init__(self, *, seed=0, epochs=200, learning_rate=0.5, l2=1e-4, batch_size=32,
                 hidden=16):
        self.seed, self.epochs, self.learning_rate = seed, epochs, learning_rate
        self.l2, self.batch_size, self.hidden = l2, batch_size, hidden
        self.labels, self.dim, self.params = [], None, None

    def fit(self, rows, vectors):
        if not rows:
            raise ValueError("cannot fit on an empty training set")
        xs, self.dim = _matrix(rows, vectors)
        self.labels = sorted({row[2] for row in rows})
        index = {label: i for i, label in enumerate(self.labels)}
        ys = [index[row[2]] for row in rows]
        rng = random.Random(self.seed)
        self._init(rng)
        order = list(range(len(xs)))
        for _ in range(self.epochs):
            rng.shuffle(order)
            for start in range(0, len(order), self.batch_size):
                batch = order[start:start + self.batch_size]
                self._step([xs[i] for i in batch], [ys[i] for i in batch])
        return self

    def predict_proba(self, rows, vectors):
        xs, _ = _matrix(rows, vectors, self.dim)
        return [self._forward(x)[-1] for x in xs]

    def predict(self, rows, vectors):
        return [self.labels[max(range(len(p)), key=p.__getitem__)]
                for p in self.predict_proba(rows, vectors)]

    def to_dict(self):
        return {"kind": self.kind, "labels": self.labels, "dim": self.dim,
                "params": self.params,
                "config": {"seed": self.seed, "epochs": self.epochs,
                           "learning_rate": self.learning_rate, "l2": self.l2,
                           "batch_size": self.batch_size, "hidden": self.hidden}}

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh)


class LogisticRegression(_Model):
    kind = "logreg"

    def _init(self, rng):
        k = len(self.labels)
        self.params = {"w": [[0.0] * self.dim for _ in range(k)], "b": [0.0] * k}

    def _forward(self, x):
        return [_softmax(_affine(self.params["w"], self.params["b"], x))]

    def _step(self, bx, by):
        w, b = self.params["w"], self.params["b"]
        k, n = len(self.labels), len(bx)
        gw = [[0.0] * self.dim for _ in range(k)]
        gb = [0.0] * k
        for x, y in zip(bx, by):
            p = self._forward(x)[0]
            for j in range(k):
                d = p[j] - (1.0 if j == y else 0.0)
                gb[j] += d
                row = gw[j]
                for i, xi in enumerate(x):
                    row[i] += d * xi
        lr = self.learning_rate
        for j in range(k):
            for i in range(self.dim):
                w[j][i] -= lr * (gw[j][i] / n + self.l2 * w[j][i])
            b[j] -= lr * gb[j] / n


class MLP(_Model):
    kind = "mlp"

    def _init(self, rng):
        k, h = len(self.labels), self.hidden
        s1, s2 = 1.0 / math.sqrt(self.dim), 1.0 / math.sqrt(h)
        self.params = {
            "w1": [[rng.uniform(-s1, s1) for _ in range(self.dim)] for _ in range(h)],
            "b1": [0.0] * h,
            "w2": [[rng.uniform(-s2, s2) for _ in range(h)] for _ in range(k)],
            "b2": [0.0] * k,
        }

    def _forward(self, x):
        p = self.params
        a = [math.tanh(v) for v in _affine(p["w1"], p["b1"], x)]
        return [a, _softmax(_affine(p["w2"], p["b2"], a))]

    def _step(self, bx, by):
        p = self.params
        k, h, n = len(self.labels), self.hidden, len(bx)
        gw1 = [[0.0] * self.dim for _ in range(h)]
        gb1 = [0.0] * h
        gw2 = [[0.0] * h for _ in range(k)]
        gb2 = [0.0] * k
        for x, y in zip(bx, by):
            a, out = self._forward(x)
            d2 = [out[j] - (1.0 if j == y else 0.0) for j in range(k)]
            for j in range(k):
                gb2[j] += d2[j]
                for u in range(h):
                    gw2[j][u] += d2[j] * a[u]
            for u in range(h):
                d1 = sum(d2[j] * p["w2"][j][u] for j in range(k)) * (1.0 - a[u] * a[u])
                gb1[u] += d1
                row = gw1[u]
                for i, xi in enumerate(x):
                    row[i] += d1 * xi
        lr, l2 = self.learning_rate, self.l2
        for w, g in ((p["w1"], gw1), (p["w2"], gw2)):
            for wr, gr in zip(w, g):
                for i in range(len(wr)):
                    wr[i] -= lr * (gr[i] / n + l2 * wr[i])
        for b, g in ((p["b1"], gb1), (p["b2"], gb2)):
            for i in range(len(b)):
                b[i] -= lr * g[i] / n


MODELS = {LogisticRegression.kind: LogisticRegression, MLP.kind: MLP}


def make_model(name, **kwargs):
    if name not in MODELS:
        raise ValueError(f"unknown model {name!r}; choose from {sorted(MODELS)}")
    return MODELS[name](**kwargs)


def load_model(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    model = make_model(data["kind"], **data["config"])
    model.labels, model.dim, model.params = data["labels"], data["dim"], data["params"]
    return model


def evaluate(model, rows, vectors):
    """Return macro-F1, per-label precision/recall/F1/support and sample sizes on rows."""
    predicted = model.predict(rows, vectors) if rows else []
    gold = [row[2] for row in rows]
    labels = sorted(set(model.labels) | set(gold))
    per_label = {}
    for label in labels:
        tp = sum(1 for g, p in zip(gold, predicted) if g == label and p == label)
        fp = sum(1 for g, p in zip(gold, predicted) if g != label and p == label)
        fn = sum(1 for g, p in zip(gold, predicted) if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1,
                            "support": tp + fn, "seen_in_train": label in model.labels}
    macro = sum(v["f1"] for v in per_label.values()) / len(per_label) if per_label else 0.0
    return {"macro_f1": macro, "per_label": per_label, "examples": len(rows),
            "documents": len({row[1] for row in rows})}


def load_vectors(path, wanted):
    """Stream a JSONL of {"node_id", "vector"}, keeping only node ids in wanted."""
    vectors = {}
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}: line {lineno}: malformed record: {exc}") from None
            if not isinstance(record, dict) or not isinstance(record.get("node_id"), str):
                raise ValueError(f"{path}: line {lineno}: expected object with str node_id")
            if record["node_id"] in wanted:
                vectors[record["node_id"]] = record.get("vector")
    return vectors


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m analysis.classifier_head")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--documents", required=True)
    parser.add_argument("--vectors", required=True)
    parser.add_argument("--model", choices=sorted(MODELS), default="logreg")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--held-out", type=float, default=0.2)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    split = build_training_set(
        CandidateLabelStore(args.labels).iter_candidates(),
        load_document_map(args.documents),
        held_out_fraction=args.held_out,
        seed=args.seed,
    )
    wanted = {row[0] for row in split["train"]} | {row[0] for row in split["held_out"]}
    vectors = load_vectors(args.vectors, wanted)
    model = make_model(args.model, seed=args.seed).fit(split["train"], vectors)
    if args.out:
        model.save(args.out)
    report = {"model": args.model, "seed": args.seed,
              "train": split["counts"]["train"],
              "held_out": evaluate(model, split["held_out"], vectors)}
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

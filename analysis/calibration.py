"""PT-04 calibrated confidence for the PT-02 move classifier head (pure stdlib).

Two calibrators over per-example probability vectors from classifier_head.predict_proba:
- "temperature": one temperature T > 0 rescaling log-probabilities, fit by minimising NLL with a
  deterministic golden-section search on log T;
- "isotonic": pool-adjacent-violators on top-class confidence vs correctness (one-vs-rest on the
  predicted class); the top probability is replaced and the rest renormalised to fill 1 - c.

reliability() bins top-class confidence into equal-width bins (count, mean confidence, accuracy);
ece() is the bin-count-weighted |accuracy - confidence|.

The CLI rebuilds the PT-01 split, divides the held-out documents in half by stable hash
(sha256(seed:calibration:document_id)), fits on one half and reports on the other. If either half
is empty it falls back to fitting and reporting on the whole held-out split and says so
("shared_split": true).

Unwired by design: the production caller is the fast layer / PT-05 ONNX export.
Residual: only labelled held-out nodes' vectors are loaded (load_vectors streams the JSONL);
memory is O(held-out examples x labels). The 100k-sentence bound is untested.
"""

import argparse
import hashlib
import json
import math
import sys

from analysis.classifier_head import load_model, load_vectors
from analysis.label_store import CandidateLabelStore
from analysis.training_set import build_training_set, load_document_map

_EPS = 1e-12


def _top(p):
    i = max(range(len(p)), key=p.__getitem__)
    return i, p[i]


def _softmax(z):
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return [v / s for v in e]


def _scale(p, temperature):
    return _softmax([math.log(max(v, _EPS)) / temperature for v in p])


def _nll(probs, labels, temperature):
    total, n = 0.0, 0
    for p, y in zip(probs, labels):
        if y is None:
            continue
        total -= math.log(max(_scale(p, temperature)[y], _EPS))
        n += 1
    return total / n if n else 0.0


class TemperatureScaling:
    method = "temperature"

    def __init__(self, temperature=1.0):
        self.temperature = temperature

    def fit(self, probs, labels, *, lo=-3.0, hi=3.0, iterations=60):
        """labels are class indices into the probability vectors; None (unseen) is skipped."""
        if not any(y is not None for y in labels):
            raise ValueError("cannot fit temperature without labelled examples")
        phi = (math.sqrt(5) - 1) / 2
        a, b = lo, hi
        c, d = b - phi * (b - a), a + phi * (b - a)
        fc, fd = _nll(probs, labels, math.exp(c)), _nll(probs, labels, math.exp(d))
        for _ in range(iterations):
            if fc <= fd:
                b, d, fd = d, c, fc
                c = b - phi * (b - a)
                fc = _nll(probs, labels, math.exp(c))
            else:
                a, c, fc = c, d, fd
                d = a + phi * (b - a)
                fd = _nll(probs, labels, math.exp(d))
        self.temperature = math.exp((a + b) / 2)
        return self

    def apply(self, probs):
        return [_scale(p, self.temperature) for p in probs]

    def to_dict(self):
        return {"method": self.method, "temperature": self.temperature}

    @classmethod
    def from_dict(cls, data):
        return cls(data["temperature"])


class IsotonicCalibration:
    method = "isotonic"

    def __init__(self, xs=None, ys=None):
        self.xs, self.ys = xs or [], ys or []

    def fit(self, probs, labels):
        pairs = sorted((_top(p)[1], 1.0 if _top(p)[0] == y else 0.0)
                       for p, y in zip(probs, labels))
        if not pairs:
            raise ValueError("cannot fit isotonic calibration on no examples")
        blocks = []  # [sum_x, sum_y, count]
        for x, y in pairs:
            blocks.append([x, y, 1])
            while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] >= blocks[-1][1] / blocks[-1][2]:
                sx, sy, n = blocks.pop()
                blocks[-1][0] += sx
                blocks[-1][1] += sy
                blocks[-1][2] += n
        self.xs = [sx / n for sx, _, n in blocks]
        self.ys = [sy / n for _, sy, n in blocks]
        return self

    def _map(self, x):
        xs, ys = self.xs, self.ys
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        for i in range(1, len(xs)):
            if x <= xs[i]:
                t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
                return ys[i - 1] + t * (ys[i] - ys[i - 1])
        return ys[-1]

    def apply(self, probs):
        out = []
        for p in probs:
            i, top = _top(p)
            c = min(max(self._map(top), _EPS), 1.0 - _EPS) if len(p) > 1 else 1.0
            rest = 1.0 - top
            k = len(p) - 1
            q = [(v / rest * (1.0 - c)) if rest > _EPS else (1.0 - c) / k for v in p] if k else [1.0]
            q[i] = c
            out.append(q)
        return out

    def to_dict(self):
        return {"method": self.method, "xs": self.xs, "ys": self.ys}

    @classmethod
    def from_dict(cls, data):
        return cls(data["xs"], data["ys"])


CALIBRATORS = {TemperatureScaling.method: TemperatureScaling,
               IsotonicCalibration.method: IsotonicCalibration}


def make_calibrator(name):
    if name not in CALIBRATORS:
        raise ValueError(f"unknown calibration method {name!r}; choose from {sorted(CALIBRATORS)}")
    return CALIBRATORS[name]()


def save_calibrator(calibrator, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(calibrator.to_dict(), fh)


def load_calibrator(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("method") not in CALIBRATORS:
        raise ValueError(f"{path}: unknown calibration method {data.get('method')!r}")
    return CALIBRATORS[data["method"]].from_dict(data)


def reliability(probs, labels, bins=10):
    """Equal-width bins on top-class confidence: [{lower, upper, count, confidence, accuracy}]."""
    if bins < 1:
        raise ValueError("bins must be >= 1")
    acc = [[0, 0.0, 0.0] for _ in range(bins)]
    for p, y in zip(probs, labels):
        i, conf = _top(p)
        b = min(int(conf * bins), bins - 1)
        acc[b][0] += 1
        acc[b][1] += conf
        acc[b][2] += 1.0 if i == y else 0.0
    return [{"lower": k / bins, "upper": (k + 1) / bins, "count": n,
             "confidence": sc / n if n else 0.0, "accuracy": sa / n if n else 0.0}
            for k, (n, sc, sa) in enumerate(acc)]


def ece(probs, labels, bins=10):
    table = reliability(probs, labels, bins)
    n = sum(b["count"] for b in table)
    if not n:
        return 0.0
    return sum(b["count"] * abs(b["accuracy"] - b["confidence"]) for b in table) / n


def _half(document_id, seed):
    digest = hashlib.sha256(f"{seed}:calibration:{document_id}".encode("utf-8")).digest()
    return digest[0] & 1


def split_held_out(rows, seed=0):
    """Divide held-out rows by document into (fit, report) halves by stable hash."""
    fit = [r for r in rows if _half(r[1], seed) == 0]
    report = [r for r in rows if _half(r[1], seed) == 1]
    return fit, report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m analysis.calibration")
    parser.add_argument("--model", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--documents", required=True)
    parser.add_argument("--vectors", required=True)
    parser.add_argument("--method", choices=sorted(CALIBRATORS), default="temperature")
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--held-out", type=float, default=0.2)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    model = load_model(args.model)
    split = build_training_set(
        CandidateLabelStore(args.labels).iter_candidates(),
        load_document_map(args.documents),
        held_out_fraction=args.held_out,
        seed=args.seed,
    )
    held = split["held_out"]
    if not held:
        raise SystemExit("held-out split is empty; nothing to calibrate")
    fit_rows, report_rows = split_held_out(held, args.seed)
    shared = not fit_rows or not report_rows
    if shared:
        fit_rows = report_rows = held
    vectors = load_vectors(args.vectors, {row[0] for row in held})
    index = {label: i for i, label in enumerate(model.labels)}

    def prepared(rows):
        return model.predict_proba(rows, vectors), [index.get(row[2]) for row in rows]

    fit_p, fit_y = prepared(fit_rows)
    rep_p, rep_y = prepared(report_rows)
    calibrator = make_calibrator(args.method).fit(fit_p, fit_y)
    after = calibrator.apply(rep_p)
    if args.out:
        save_calibrator(calibrator, args.out)
    report = {
        "method": args.method, "seed": args.seed, "bins": args.bins,
        "calibrator": calibrator.to_dict(),
        "shared_split": shared,
        "note": ("calibration fit and evaluation share the held-out split" if shared else
                 "held-out documents halved by stable hash: fit on one half, reported on the other"),
        "fit": {"examples": len(fit_rows), "documents": len({r[1] for r in fit_rows})},
        "report": {"examples": len(report_rows), "documents": len({r[1] for r in report_rows})},
        "ece_before": ece(rep_p, rep_y, args.bins),
        "ece_after": ece(after, rep_y, args.bins),
        "reliability_before": reliability(rep_p, rep_y, args.bins),
        "reliability_after": reliability(after, rep_y, args.bins),
    }
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

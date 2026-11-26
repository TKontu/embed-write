"""PT-04 tests; all probabilities, vectors and labels are LLM-built synthetic fixtures."""

import json
import math
import os
import random
import subprocess
import sys
import tempfile
import unittest

from analysis.calibration import (IsotonicCalibration, TemperatureScaling, ece, load_calibrator,
                                  make_calibrator, reliability, save_calibrator, split_held_out)
from analysis.label_store import CandidateLabelStore
from tests.test_classifier_head import LABELS, vector_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _softmax(z):
    m = max(z)
    e = [math.exp(v - m) for v in z]
    return [v / sum(e) for v in e]


def _sample(p, rng):
    r, acc = rng.random(), 0.0
    for i, v in enumerate(p):
        acc += v
        if r < acc:
            return i
    return len(p) - 1


def synthetic(n=4000, sharpen=3.0, seed=7):
    """Labels drawn from true probs; reported probs are sharpened (over-confident) if sharpen>1."""
    rng = random.Random(seed)
    probs, labels = [], []
    for _ in range(n):
        logits = [rng.gauss(0.0, 1.0) for _ in range(3)]
        labels.append(_sample(_softmax(logits), rng))
        probs.append(_softmax([v * sharpen for v in logits]))
    return probs, labels


class CalibrationTest(unittest.TestCase):
    def test_temperature_fits_above_one_and_lowers_ece(self):
        probs, labels = synthetic()
        cal = TemperatureScaling().fit(probs, labels)
        self.assertGreater(cal.temperature, 1.0)
        self.assertAlmostEqual(cal.temperature, 3.0, delta=0.5)
        self.assertLess(ece(cal.apply(probs), labels), ece(probs, labels) / 2)

    def test_isotonic_lowers_ece(self):
        probs, labels = synthetic()
        fit_p, fit_y = probs[:2000], labels[:2000]
        test_p, test_y = synthetic(seed=8)
        cal = make_calibrator("isotonic").fit(fit_p, fit_y)
        after = cal.apply(test_p)
        self.assertLess(ece(after, test_y), ece(test_p, test_y) / 2)
        for p in after:
            self.assertAlmostEqual(sum(p), 1.0, places=9)

    def test_calibrated_data_ece_near_zero_and_bins_sum(self):
        probs, labels = synthetic(n=20000, sharpen=1.0, seed=3)
        self.assertLess(ece(probs, labels), 0.02)
        table = reliability(probs, labels, bins=15)
        self.assertEqual(len(table), 15)
        self.assertEqual(sum(b["count"] for b in table), 20000)

    def test_deterministic(self):
        probs, labels = synthetic()
        for method in ("temperature", "isotonic"):
            a = make_calibrator(method).fit(probs, labels).to_dict()
            b = make_calibrator(method).fit(probs, labels).to_dict()
            self.assertEqual(a, b)
        rows = [(f"n{i}", f"doc{i % 9}", "claim", "x") for i in range(30)]
        self.assertEqual(split_held_out(rows, 4), split_held_out(rows, 4))

    def test_save_load_round_trip(self):
        probs, labels = synthetic(n=500)
        with tempfile.TemporaryDirectory() as tmp:
            for method in ("temperature", "isotonic"):
                cal = make_calibrator(method).fit(probs, labels)
                path = os.path.join(tmp, f"{method}.json")
                save_calibrator(cal, path)
                loaded = load_calibrator(path)
                self.assertIsInstance(loaded, type(cal))
                self.assertEqual(loaded.apply(probs[:20]), cal.apply(probs[:20]))

    def test_unknown_method_and_unseen_label(self):
        with self.assertRaises(ValueError):
            make_calibrator("platt")
        # None marks a held-out label the model never saw: skipped by NLL, incorrect in ECE.
        cal = TemperatureScaling().fit([[0.9, 0.1], [0.8, 0.2]], [0, None])
        self.assertGreater(cal.temperature, 0.0)
        self.assertEqual(reliability([[0.9, 0.1]], [None], bins=2)[1]["accuracy"], 0.0)
        IsotonicCalibration().fit([[0.9, 0.1]], [None])

    def test_cli_end_to_end(self):
        rng = random.Random(5)
        with tempfile.TemporaryDirectory() as tmp:
            labels = os.path.join(tmp, "labels.jsonl")
            docs = os.path.join(tmp, "docs.jsonl")
            vecs = os.path.join(tmp, "vectors.jsonl")
            model = os.path.join(tmp, "model.json")
            cal = os.path.join(tmp, "cal.json")
            store = CandidateLabelStore(labels)
            with open(docs, "w") as dfh, open(vecs, "w") as vfh:
                for d in range(30):
                    for s in range(3):
                        node, label = f"d{d}-s{s}", LABELS[s]
                        store.append(node, label, "m1", 1)
                        dfh.write(json.dumps({"node_id": node, "document_id": f"doc{d}"}) + "\n")
                        vfh.write(json.dumps({"node_id": node,
                                              "vector": vector_for(label, rng)}) + "\n")
            common = ["--labels", labels, "--documents", docs, "--vectors", vecs,
                      "--seed", "1", "--held-out", "0.4"]
            subprocess.run([sys.executable, "-m", "analysis.classifier_head", *common,
                            "--out", model], cwd=ROOT, capture_output=True, check=True)
            for method in ("temperature", "isotonic"):
                proc = subprocess.run(
                    [sys.executable, "-m", "analysis.calibration", "--model", model, *common,
                     "--method", method, "--bins", "5", "--out", cal],
                    cwd=ROOT, capture_output=True, text=True, check=True)
                report = json.loads(proc.stdout)
                self.assertIn("ece_before", report)
                self.assertIn("ece_after", report)
                self.assertEqual(len(report["reliability_before"]), 5)
                self.assertEqual(sum(b["count"] for b in report["reliability_after"]),
                                 report["report"]["examples"])
                self.assertGreater(report["report"]["documents"], 0)
                self.assertIn("shared_split", report)
                self.assertEqual(load_calibrator(cal).method, method)


if __name__ == "__main__":
    unittest.main()

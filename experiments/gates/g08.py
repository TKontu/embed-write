"""G-08 gate: meaning-preservation scorer against held-out rewrite pairs (G-08.3).

Takes held-out evaluation RewritePairs (config["pairs"], or a zero-argument
config["loader"] hook returning them) and a separate, required calibration split
(config["calibration_pairs"]; never defaulted to the evaluation set). The two splits
must be non-empty and share no pair_id. The silent-filter threshold is calibrated on
the calibration split with experiments.metrics.meaning.calibrate (target_precision,
default 0.95). If calibration finds no threshold, the G-08 failure policy applies:
the threshold is recorded as null, "filter" is "disabled" (nothing is filtered), and
the evaluation set is still scored at config["threshold"] (default 0.5).

The arm is config["arm"] (default meaning.number_unit_arm); entailment and AlignScore
arms need local models and can be passed in via meaning.combine. Every metric row
carries n, interval and method (ST-02).

Run only through experiments.runner.run_gate, which refuses without a confirmed
preregistration record for "g08". Production caller: run_gate on the held-out pairs
once G-08.1 (pairs) and the g08 preregistration exist; no corpus I/O here.
Memory: O(pairs) — both splits and their per-pair scores are materialised.
"""
from __future__ import annotations

import random
from typing import Any, Mapping

from experiments.metrics.meaning import (
    RewritePair, calibrate, number_unit_arm, score, wilson)

gate_id = "g08"


def _interval(iv) -> list | None:
    return None if iv is None else [round(iv[0], 6), round(iv[1], 6)]


def _pairs(config: Mapping[str, Any], key: str) -> list:
    if key == "pairs" and key not in config and "loader" in config:
        value = config["loader"]()
    else:
        value = config.get(key)
    if value is None:
        hint = " or a loader hook" if key == "pairs" else ""
        raise ValueError(f"g08 requires config[{key!r}]{hint}")
    pairs = list(value)
    if not pairs:
        raise ValueError(f"g08 requires a non-empty {key} sequence")
    for p in pairs:
        if not isinstance(p, RewritePair):
            raise ValueError(f"{key} must contain RewritePair, got {type(p).__name__}")
    return pairs


def _bootstrap_ba(scored: list, threshold: float, rng: random.Random,
                  n_resamples: int) -> tuple[list | None, int]:
    k = len(scored)
    values = []
    for _ in range(n_resamples):
        tp = pos = tn = neg = 0
        for _ in range(k):
            s, keep = scored[rng.randrange(k)]
            if keep:
                pos += 1
                tp += s >= threshold
            else:
                neg += 1
                tn += s < threshold
        if pos and neg:  # balanced accuracy undefined without both classes
            values.append((tp / pos + tn / neg) / 2)
    if not values:
        return None, 0
    values.sort()
    m = len(values)
    return [round(values[int(0.025 * m)], 6),
            round(values[max(int(0.975 * m) - 1, 0)], 6)], m


def run(rng: random.Random, config: Mapping[str, Any]) -> dict:
    evaluation = _pairs(config, "pairs")
    calibration = _pairs(config, "calibration_pairs")
    overlap = sorted({p.pair_id for p in evaluation} & {p.pair_id for p in calibration})
    if overlap:
        raise ValueError(f"pair_id in both evaluation and calibration splits: {overlap[:5]}")
    arm = config.get("arm", number_unit_arm)
    target = float(config.get("target_precision", 0.95))
    n_resamples = int(config.get("n_resamples", 1000))

    cal = calibrate(calibration, arm, target_precision=target)
    if cal is None:
        threshold, filt = float(config.get("threshold", 0.5)), "disabled"
    else:
        threshold, filt = cal.threshold, "enabled"
    cal_record = {"target_precision": target, "n": len(calibration),
                  "threshold": None if cal is None else cal.threshold,
                  "precision": None if cal is None else round(cal.precision, 6),
                  "n_flagged": None if cal is None else cal.n_flagged}

    res = score(evaluation, arm, threshold)
    scored = [(float(arm(p.original, p.candidate)), p.preserved) for p in evaluation]
    flagged = [keep for s, keep in scored if s < threshold]
    correct_flags = sum(not k for k in flagged)
    ba_iv, ba_m = _bootstrap_ba(scored, threshold, rng, n_resamples)

    def r(v):
        return None if v is None else round(v, 6)

    metrics = [
        {"metric": "tpr", "value": r(res.tpr.value), "n": res.tpr.n,
         "interval": _interval(res.tpr.interval), "method": "wilson95"},
        {"metric": "tnr", "value": r(res.tnr.value), "n": res.tnr.n,
         "interval": _interval(res.tnr.interval), "method": "wilson95"},
        {"metric": "balanced_accuracy", "value": r(res.balanced_accuracy), "n": res.n,
         "interval": ba_iv, "valid_resamples": ba_m,
         "method": f"bootstrap95_{n_resamples}"},
        {"metric": "flagged_precision", "value": r(correct_flags / len(flagged)) if flagged else None,
         "n": len(flagged), "interval": _interval(wilson(correct_flags, len(flagged))),
         "method": "wilson95"},
    ]
    return {"metrics": metrics, "calibration": cal_record, "threshold": threshold,
            "filter": filt, "n_eval": len(evaluation)}


run.gate_id = gate_id

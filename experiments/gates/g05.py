"""G-05 gate: sequence-fit detectors against seeded perturbations (G-05.1/G-05.2).

Takes LabelledSection sequences (config["sections"], or a zero-argument
config["loader"] hook returning them), builds Detectors from reference
sections (config["reference_sections"], default: the same sections),
perturbs the held-out sections with analysis.perturb.perturb seeded from the
runner rng, and scores perturbed and unperturbed sections with
experiments.metrics.sequence_fit.score. Every metric row carries n and a 95%
interval (ST-02); the perturbation log carries the ground truth of each change.

Run only through experiments.runner.run_gate, which refuses without a confirmed
preregistration record for "g05". Production caller: run_gate on the held-out
split once the corpus and preregistration exist (G-05.2 [H]); no corpus I/O
here. Memory: the held-out sections are materialised (O(sections)) so they can
be passed twice; the perturbation log is O(perturbations).
"""
from __future__ import annotations

import math
import random
from typing import Any, Mapping

from analysis.detectors import Detectors
from analysis.expected_moves import ExpectedMoves
from analysis.perturb import KINDS, log_record, perturb
from analysis.transitions import LabelledSection, TransitionStats
from experiments.metrics.sequence_fit import score, to_record

gate_id = "g05"

_Z95 = 1.959963984540054


def _wilson(successes: int, n: int) -> list | None:
    if not n:
        return None
    p = successes / n
    denom = 1 + _Z95 ** 2 / n
    centre = (p + _Z95 ** 2 / (2 * n)) / denom
    half = _Z95 * math.sqrt(p * (1 - p) / n + _Z95 ** 2 / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)]


def _bootstrap_mean(values: list, rng: random.Random, n_resamples: int) -> list | None:
    k = len(values)
    if not k:
        return None
    means = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k
                   for _ in range(n_resamples))
    return [round(means[int(0.025 * n_resamples)], 6),
            round(means[max(int(0.975 * n_resamples) - 1, 0)], 6)]


def _sections(config: Mapping[str, Any], key: str, default=None) -> list:
    if key == "sections" and key not in config and "loader" in config:
        value = config["loader"]()
    else:
        value = config.get(key, default)
    if value is None:
        raise ValueError(f"g05 requires config[{key!r}] or a loader hook")
    sections = list(value)
    if not sections:
        raise ValueError(f"g05 requires a non-empty {key} sequence")
    for s in sections:
        if not isinstance(s, LabelledSection):
            raise TypeError(f"{key} must contain LabelledSection, got {type(s).__name__}")
    return sections


def run(rng: random.Random, config: Mapping[str, Any]) -> dict:
    held = _sections(config, "sections")
    reference = _sections(config, "reference_sections", held)
    n_resamples = int(config.get("n_resamples", 1000))
    detectors = Detectors(
        TransitionStats.from_sections(reference),
        ExpectedMoves.from_sections(reference),
        order_threshold=config.get("order_threshold", 0.05))
    perturb_seed = rng.randrange(2 ** 32)
    pairs = list(perturb(held, kinds=tuple(config.get("kinds", KINDS)),
                         foreign_moves=tuple(config.get("foreign_moves", ("__foreign__",))),
                         seed=perturb_seed))
    fit = score(pairs, held, detectors)

    per_report: dict = {}
    for s in held:
        per_report[s.document_id] = per_report.get(s.document_id, 0) + len(detectors.detect(s))
    counts = [per_report[d] for d in sorted(per_report)]
    assert sum(counts) == fit.false_flags_unperturbed

    metrics = [
        {"metric": "precision", "value": fit.precision, "n": fit.flags_on_perturbed,
         "interval": _wilson(fit.true_flags, fit.flags_on_perturbed), "method": "wilson95"},
        {"metric": "recall", "value": fit.recall, "n": fit.perturbations,
         "interval": _wilson(fit.detected, fit.perturbations), "method": "wilson95"},
        {"metric": "false_flags_per_unperturbed_report",
         "value": round(sum(counts) / len(counts), 6), "n": len(counts),
         "count": fit.false_flags_unperturbed, "max": fit.max_false_flags_per_report,
         "interval": _bootstrap_mean(counts, rng, n_resamples),
         "method": f"bootstrap95_mean_{n_resamples}"},
    ]
    return {
        "metrics": metrics,
        "score": to_record(fit),
        "perturb_seed": perturb_seed,
        "perturbation_log": [log_record(p) for _, p in pairs],
    }


run.gate_id = gate_id

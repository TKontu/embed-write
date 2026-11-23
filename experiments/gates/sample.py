"""Synthetic sample gate: exercises the runner with built-in synthetic data only."""
from __future__ import annotations

import random
from typing import Any, Mapping

gate_id = "sample"

_SYNTHETIC = [0.12, 0.47, 0.33, 0.91, 0.05, 0.68, 0.24, 0.79, 0.56, 0.40]


def run(rng: random.Random, config: Mapping[str, Any]) -> dict:
    n = int(config.get("n_resamples", 200))
    k = len(_SYNTHETIC)
    means = sorted(sum(rng.choice(_SYNTHETIC) for _ in range(k)) / k for _ in range(n))
    return {
        "metric": "bootstrap_mean",
        "value": round(sum(_SYNTHETIC) / k, 6),
        "n": k,
        "interval": [round(means[int(0.025 * n)], 6), round(means[int(0.975 * n) - 1], 6)],
        "resample_head": [round(m, 6) for m in means[:3]] + [round(rng.random(), 6)],
    }


run.gate_id = gate_id

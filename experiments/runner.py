"""Reproducible gate runner: explicit seed, pinned model versions, recorded hardware.

Production callers: the gate modules of todo-01 (unwired by design until G-01 runs, row X-00).
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import random
from typing import Any, Callable, Mapping

from experiments.preregistration import DEFAULT_ROOT, require_confirmed

# Only the synthetic demonstration gate is exempt; callers cannot override this.
exempt = ("sample",)

GateFn = Callable[[random.Random, Mapping[str, Any]], Any]


def build_manifest(gate: str, seed: int, config: Mapping[str, Any]) -> dict:
    return {
        "gate": gate,
        "seed": seed,
        "model_versions": dict(config.get("model_versions", {})),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def run_gate(
    gate_fn: GateFn, *, seed: int, config: Mapping[str, Any],
    preregistration_root=DEFAULT_ROOT,
) -> dict:
    """Run ``gate_fn(rng, config)`` with a ``random.Random(seed)``; return result + manifest."""
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an int")
    gate = getattr(gate_fn, "gate_id", None) or gate_fn.__module__.rsplit(".", 1)[-1]
    record = None if gate in exempt else require_confirmed(gate, root=preregistration_root)
    manifest = build_manifest(gate, seed, config)
    if record is not None:
        manifest["preregistration"] = record
    rng = random.Random(seed)
    return {"manifest": manifest, "result": gate_fn(rng, config)}


def serialize(run: Mapping[str, Any]) -> str:
    """Canonical JSON: sorted keys, fixed separators, so equal runs are byte-identical."""
    return json.dumps(run, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

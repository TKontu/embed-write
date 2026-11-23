"""Nightly small-corpus run (CE-02): run the available gates offline and apply outcomes to flags.

``python3 -m experiments.nightly [--previous PATH] [--flags PATH] [--out PATH]``

For each gate: run it through ``experiments.runner.run_gate`` (which refuses a gate without a
confirmed preregistration; such a gate is reported ``skipped`` with the refusal message, never as
passed or failed), compare its run descriptor with ``--previous`` via
``experiments.continuous.rerun_required``, and apply the outcome with
``FlagRegistry.apply_rerun`` (which only ever disables; a pass never enables a flag, I6).

Pass criterion. A gate *regresses* when its result carries a pass criterion that it fails:

* every gate must be reproducible: two runs with the same seed must give byte-identical
  ``serialize`` output of the result (the manifest carries a timestamp and is excluded);
* a result that is a dict with a boolean ``"passed"`` key fails when it is ``False``.

For the synthetic ``sample`` gate the only criterion is reproducibility.

Run descriptor (input of ``rerun_required``): ``modelVersion`` is the canonical JSON of the
config's ``model_versions``, ``inventoryVersion`` the config's ``inventory_version`` (or
``"none"``), ``method`` the gate function's ``module.qualname``. With no ``--previous`` entry for a
gate every key counts as changed.

A gate that raises is recorded as regressed (``crashed: ...``) and the run continues.

Exit codes: 0 no gate regressed, 1 at least one regressed, 2 bad input. ``--flags`` is updated in
place only when given; this module never chooses a persistent registry location. Offline (I9);
memory O(gates + flags). Called by ``.github/workflows/nightly.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Sequence

from experiments.continuous import FlagRegistry, rerun_required
from experiments.gates import sample
from experiments.preregistration import DEFAULT_ROOT, PreregistrationError
from experiments.runner import run_gate, serialize

SEED = 20240101
DEFAULT_GATES: tuple[tuple[Any, Mapping[str, Any]], ...] = ((sample.run, {"n_resamples": 200}),)


class InputError(ValueError):
    """Bad --previous / --flags input (exit 2)."""


def gate_name(gate_fn) -> str:
    return getattr(gate_fn, "gate_id", None) or gate_fn.__module__.rsplit(".", 1)[-1]


def descriptor(gate_fn, config: Mapping[str, Any]) -> dict:
    return {
        "modelVersion": json.dumps(dict(config.get("model_versions", {})), sort_keys=True),
        "inventoryVersion": str(config.get("inventory_version", "none")),
        "method": f"{gate_fn.__module__}.{getattr(gate_fn, '__qualname__', repr(gate_fn))}",
    }


def evaluate(gate_fn, config, *, seed, preregistration_root) -> tuple[str, str]:
    """Return ``(status, detail)`` with status passed / regressed / skipped.

    A gate that raises an ``Exception`` regresses with detail ``crashed: <Type>: <message>``;
    ``KeyboardInterrupt`` / ``SystemExit`` propagate."""
    try:
        first = run_gate(gate_fn, seed=seed, config=config, preregistration_root=preregistration_root)
    except PreregistrationError as error:
        return "skipped", str(error)
    except Exception as error:
        return "regressed", f"crashed: {type(error).__name__}: {error}"
    try:
        second = run_gate(gate_fn, seed=seed, config=config, preregistration_root=preregistration_root)
    except Exception as error:
        return "regressed", f"crashed: {type(error).__name__}: {error}"
    if serialize({"result": first["result"]}) != serialize({"result": second["result"]}):
        return "regressed", "not reproducible: same seed gave different serialized results"
    result = first["result"]
    if isinstance(result, dict) and result.get("passed") is False:
        return "regressed", "result reports passed=false"
    return "passed", "reproducible" + ("; passed=true" if isinstance(result, dict) and result.get("passed") is True else "")


def run_nightly(
    gates: Sequence[tuple[Any, Mapping[str, Any]]] = DEFAULT_GATES,
    *, previous: Mapping[str, Any] | None = None, registry: FlagRegistry | None = None,
    seed: int = SEED, preregistration_root=DEFAULT_ROOT,
) -> dict:
    prev_gates = (previous or {}).get("gates", {})
    out: dict[str, dict] = {}
    for gate_fn, config in gates:
        name = gate_name(gate_fn)
        desc = descriptor(gate_fn, config)
        prev_entry = prev_gates.get(name, {})
        prev_desc = prev_entry.get("descriptor", {}) if isinstance(prev_entry, dict) else {}
        status, detail = evaluate(gate_fn, config, seed=seed, preregistration_root=preregistration_root)
        notes: list[str] = []
        if registry is not None and status != "skipped":
            notes = registry.apply_rerun(name, status == "passed", detail)
        out[name] = {
            "status": status,
            "detail": detail,
            "descriptor": desc,
            "rerun_reasons": rerun_required(prev_desc if isinstance(prev_desc, dict) else {}, desc),
            "notes": notes,
        }
    return {"seed": seed, "regressed": any(g["status"] == "regressed" for g in out.values()), "gates": out}


def _load_json(path: str, what: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"{what}: cannot read JSON at {path}: {error}") from error


def main(argv: Sequence[str] | None = None, *, gates=DEFAULT_GATES, preregistration_root=DEFAULT_ROOT) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m experiments.nightly", description=__doc__.splitlines()[0])
    parser.add_argument("--previous", help="prior summary JSON")
    parser.add_argument("--flags", help="FlagRegistry JSON, updated in place")
    parser.add_argument("--out", help="summary JSON path (default stdout)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        previous = None
        if args.previous:
            previous = _load_json(args.previous, "--previous")
            if not isinstance(previous, dict) or not isinstance(previous.get("gates", {}), dict):
                raise InputError("--previous: must be an object with a 'gates' object")
        registry = None
        if args.flags:
            data = _load_json(args.flags, "--flags")
            if not isinstance(data, dict):
                raise InputError("--flags: must be an object")
            try:
                registry = FlagRegistry.from_dict(data)
            except ValueError as error:
                raise InputError(f"--flags: {error}") from error
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    summary = run_nightly(gates, previous=previous, registry=registry, preregistration_root=preregistration_root)
    if registry is not None:
        with open(args.flags, "w", encoding="utf-8") as fh:
            json.dump(registry.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 1 if summary["regressed"] else 0


if __name__ == "__main__":
    sys.exit(main())

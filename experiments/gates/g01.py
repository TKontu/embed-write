"""G-01 gate: annotation agreement, expert vs LLM and expert vs self (G-01.5).

Config (all label maps are sentence_id -> label):
  expert         the AN-03 expert pass (required)
  llm            the G-01.4 LLM labels (required)
  expert_repeat  the AN-04 expert re-annotation (optional; self kappa is null, n 0 without it)
  labels         explicit label order: inventory moves plus the other label (required)
  other_label    default "other"; must be in labels
  split, doc_of  optional DocumentSplit and sentence_id -> doc id; every labelled sentence's
                 document goes through split.check_eval (SplitLeakError on train/unassigned)
  thresholds     optional {"kappa_expert_llm", "kappa_expert_self", "other_share"}; defaults
                 are the proposed G-01 values (G-01.1 is [H]) and reported as "proposed"
  n_resamples    bootstrap resamples for the kappa 95 % interval (default 1000)

Pairs are the intersection of sentence ids; non-overlapping ids are reported as counts in
"pairing". A label outside labels raises ValueError. The output carries a per-threshold
"verdict_hint" (meets / misses / n/a), never a gate status.

Run only through experiments.runner.run_gate (requires a confirmed "g01" preregistration).
Unwired by design until G-01.2-G-01.4 data exists; G-01.6 runs it. No corpus or store I/O.
Memory: O(sentences); bootstrap time O(n * n_resamples).
"""
from __future__ import annotations

import random
from typing import Any, Mapping

from experiments.metrics.agreement import cohens_kappa, confusion_matrix, per_class_f1

gate_id = "g01"

PROPOSED_THRESHOLDS = {"kappa_expert_llm": 0.6, "kappa_expert_self": 0.7, "other_share": 0.15}


def _labels_map(config: Mapping[str, Any], key: str, labels: set, required: bool) -> dict | None:
    value = config.get(key)
    if value is None:
        if required:
            raise ValueError(f"g01 requires config[{key!r}]")
        return None
    out = dict(value)
    for sid, label in out.items():
        if label not in labels:
            raise ValueError(f"{key}[{sid!r}] has label {label!r} outside labels")
    return out


def _pair(a: dict, b: dict) -> tuple[list, list, list, dict]:
    ids = sorted(a.keys() & b.keys())
    counts = {"paired": len(ids), "only_a": len(a.keys() - b.keys()),
              "only_b": len(b.keys() - a.keys())}
    return ids, [a[i] for i in ids], [b[i] for i in ids], counts


def _bootstrap_kappa(x: list, y: list, rng: random.Random, n_resamples: int) -> list | None:
    k = len(x)
    if not k or n_resamples <= 0:
        return None
    values = []
    for _ in range(n_resamples):
        idx = [rng.randrange(k) for _ in range(k)]
        values.append(cohens_kappa([x[i] for i in idx], [y[i] for i in idx]))
    values.sort()
    m = len(values)
    return [round(values[int(0.025 * m)], 6), round(values[max(int(0.975 * m) - 1, 0)], 6)]


def _hint(value, threshold: float, higher_is_better: bool) -> str:
    if value is None:
        return "n/a"
    ok = value >= threshold if higher_is_better else value <= threshold
    return "meets" if ok else "misses"


def _r(v):
    return None if v is None else round(v, 6)


def run(rng: random.Random, config: Mapping[str, Any]) -> dict:
    if config.get("labels") is None:
        raise ValueError("g01 requires config['labels'] (explicit order)")
    labels = list(config["labels"])
    if len(set(labels)) != len(labels):
        raise ValueError("labels must be unique")
    other = config.get("other_label", "other")
    if other not in labels:
        raise ValueError(f"other label {other!r} must be in labels")
    label_set = set(labels)
    expert = _labels_map(config, "expert", label_set, True)
    llm = _labels_map(config, "llm", label_set, True)
    repeat = _labels_map(config, "expert_repeat", label_set, False)

    split = config.get("split")
    if split is not None:
        doc_of = config.get("doc_of")
        if doc_of is None:
            raise ValueError("g01 split requires config['doc_of']")
        sids = set(expert) | set(llm) | set(repeat or {})
        missing = sorted(s for s in sids if s not in doc_of)
        if missing:
            raise ValueError(f"doc_of lacks sentence ids: {missing[:5]}")
        split.check_eval(sorted({doc_of[s] for s in sids}))

    if "thresholds" in config:
        thresholds = {**PROPOSED_THRESHOLDS, **dict(config["thresholds"])}
        source = "config"
    else:
        thresholds, source = dict(PROPOSED_THRESHOLDS), "proposed"
    n_resamples = int(config.get("n_resamples", 1000))
    method = f"cohens_kappa_bootstrap95_{n_resamples}"

    _, e, l, c = _pair(expert, llm)
    pairing = {"expert_llm": {"paired": c["paired"], "only_expert": c["only_a"],
                              "only_llm": c["only_b"]}}
    if not e:
        raise ValueError("expert and llm share no sentence ids")
    kappa_el = cohens_kappa(e, l)
    metrics = [{"metric": "kappa_expert_llm", "value": _r(kappa_el), "n": len(e),
                "interval": _bootstrap_kappa(e, l, rng, n_resamples), "method": method,
                "verdict_hint": _hint(kappa_el, thresholds["kappa_expert_llm"], True)}]

    if repeat is None:
        metrics.append({"metric": "kappa_expert_self", "value": None, "n": 0, "interval": None,
                        "method": method, "verdict_hint": "n/a"})
        pairing["expert_self"] = None
    else:
        _, a, b, c = _pair(expert, repeat)
        pairing["expert_self"] = {"paired": c["paired"], "only_expert": c["only_a"],
                                  "only_repeat": c["only_b"]}
        ks = cohens_kappa(a, b) if a else None
        metrics.append({"metric": "kappa_expert_self", "value": _r(ks), "n": len(a),
                        "interval": _bootstrap_kappa(a, b, rng, n_resamples), "method": method,
                        "verdict_hint": _hint(ks, thresholds["kappa_expert_self"], True)})

    for name, source_map in (("expert", expert), ("llm", llm)):
        n = len(source_map)
        share = sum(v == other for v in source_map.values()) / n if n else None
        metrics.append({"metric": f"other_share_{name}", "value": _r(share), "n": n,
                        "interval": None, "method": "proportion_all_labelled",
                        "verdict_hint": _hint(share, thresholds["other_share"], False)})

    _, matrix = confusion_matrix(e, l, labels=labels)
    f1 = per_class_f1(e, l)
    zero = {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    per_move = {lab: {k: _r(v) for k, v in f1.get(lab, zero).items()} for lab in labels}
    return {"metrics": metrics,
            "confusion": {"labels": labels, "rows": "expert", "columns": "llm",
                          "matrix": matrix, "per_move": per_move},
            "pairing": pairing, "thresholds": thresholds, "thresholds_source": source,
            "n_resamples": n_resamples}


run.gate_id = gate_id

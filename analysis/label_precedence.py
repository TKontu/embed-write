"""DS-02 label precedence: expert corrections outrank slow-layer labels, which outrank nothing.

Pure resolver, unwired by design: DS-01 (stored slow-layer verdicts) and PT-01 (training set)
are the intended consumers.
"""

import math

# Ranked highest first.
SOURCES = ("expert", "slow_layer")
_RANK = {source: rank for rank, source in enumerate(SOURCES)}


def _timestamp(candidate, index):
    ts = candidate.get("timestamp")
    if ts is None:
        return -math.inf
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        raise ValueError(f"candidate {index}: timestamp must be int or float")
    return ts


def _validate(candidate, index):
    for key in ("node_id", "label"):
        if candidate.get(key) is None:
            raise ValueError(f"candidate {index}: missing {key}")
    source = candidate.get("source")
    if source not in _RANK:
        raise ValueError(f"candidate {index}: unknown source {source!r}")
    if source == "slow_layer":
        mv = candidate.get("model_version")
        if not isinstance(mv, str) or not mv:
            raise ValueError(f"candidate {index}: slow_layer label needs a non-empty model_version")


def resolve_labels(candidates):
    """Return node_id -> winning candidate.

    Highest-ranked source wins; within a source the latest timestamp wins (a missing timestamp
    sorts earliest); ties go to the later input position. Nodes without candidates are absent.
    The iterable is consumed once; inputs are not mutated and winners are returned as given.
    """
    best = {}  # node_id -> (key, candidate)
    for index, candidate in enumerate(candidates):
        _validate(candidate, index)
        key = (-_RANK[candidate["source"]], _timestamp(candidate, index), index)
        node_id = candidate["node_id"]
        current = best.get(node_id)
        if current is None or key > current[0]:
            best[node_id] = (key, candidate)
    return {node_id: candidate for node_id, (_, candidate) in best.items()}

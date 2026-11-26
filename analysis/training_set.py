"""PT-01 training set: resolved candidate labels split into train/held-out by document.

Expert labels outrank slow_layer labels via analysis.label_precedence.resolve_labels. Every
document lands wholly in one split; the split is keyed on sha256(seed:document_id), so it does
not depend on input order or Python's hash().

Unwired by design until PT-02 (classifier head) consumes build_training_set.
Residual: memory holds one winner per node (resolve_labels) plus the node->document map; the
100 000-node bound is untested.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter

from analysis.label_precedence import resolve_labels
from analysis.label_store import CandidateLabelStore


def _held_out(document_id, seed, fraction):
    digest = hashlib.sha256(f"{seed}:{document_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < fraction


def _counts(rows):
    return {
        "documents": len({row[1] for row in rows}),
        "examples": len(rows),
        "labels": dict(sorted(Counter(row[2] for row in rows).items())),
    }


def build_training_set(candidates, document_of, *, held_out_fraction=0.2, seed=0):
    """Return {"train": [...], "held_out": [...], "counts": {"train": .., "held_out": ..}}.

    Rows are (node_id, document_id, label, source) sorted by (document_id, node_id).
    document_of maps node_id -> document_id; a winning node without a mapping raises ValueError.
    """
    if isinstance(held_out_fraction, bool) or not 0.0 <= held_out_fraction <= 1.0:
        raise ValueError("held_out_fraction must be within [0, 1]")
    winners = resolve_labels(candidates)
    train, held_out = [], []
    for node_id in sorted(winners):
        if node_id not in document_of:
            raise ValueError(f"node {node_id!r} has no document mapping")
        document_id = document_of[node_id]
        winner = winners[node_id]
        row = (node_id, document_id, winner["label"], winner["source"])
        (held_out if _held_out(document_id, seed, held_out_fraction) else train).append(row)
    train.sort(key=lambda r: (r[1], r[0]))
    held_out.sort(key=lambda r: (r[1], r[0]))
    return {
        "train": train,
        "held_out": held_out,
        "counts": {"train": _counts(train), "held_out": _counts(held_out)},
    }


def load_document_map(path):
    """Stream a JSONL of {"node_id", "document_id"} into a dict; conflicts raise ValueError."""
    mapping = {}
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}: line {lineno}: malformed record: {exc}") from None
            if not isinstance(record, dict):
                raise ValueError(f"{path}: line {lineno}: not a JSON object")
            node_id, document_id = record.get("node_id"), record.get("document_id")
            if not isinstance(node_id, str) or not isinstance(document_id, str):
                raise ValueError(f"{path}: line {lineno}: node_id and document_id must be str")
            if mapping.get(node_id, document_id) != document_id:
                raise ValueError(f"{path}: line {lineno}: node {node_id!r} mapped to two documents")
            mapping[node_id] = document_id
    return mapping


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m analysis.training_set")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--documents", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--held-out", type=float, default=0.2)
    args = parser.parse_args(argv)
    result = build_training_set(
        CandidateLabelStore(args.labels).iter_candidates(),
        load_document_map(args.documents),
        held_out_fraction=args.held_out,
        seed=args.seed,
    )
    json.dump(result["counts"], sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

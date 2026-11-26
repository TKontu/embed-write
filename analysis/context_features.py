"""PT-03 context features for the move classifier (pure stdlib).

An augmented feature vector is the sentence's own vector, optionally followed by the previous and
next sentence vectors *within the same section* (zero-padded at section boundaries or when a
neighbour has no vector), optionally followed by a one-hot section type. Invariant I2 holds:
neighbour features are other sentence vectors, never paragraph/section vectors. The section-type
vocabulary is built from train rows only; an unknown type encodes as all zeros.

ablate() trains the PT-02 classifier head with and without context on the same document split and
reports held-out macro-F1 for each; the verdict is "keep" only if context improves held-out
macro-F1 by more than margin (default 0), otherwise "drop".

Context map: JSONL of {"node_id", "document_id", "section_id", "section_type", "index"}.

Unwired by design until PT-05 / the fast layer consumes it.
Residual: context and vectors are streamed and kept only for labelled nodes and their in-section
neighbours; memory is O(examples x (3 x dim + section types)). The 100k-sentence bound is untested
and pure-Python training at that size will be slow.
"""

import argparse
import json
import sys

from analysis.classifier_head import MODELS, evaluate, load_vectors, make_model
from analysis.label_store import CandidateLabelStore
from analysis.training_set import build_training_set, load_document_map

_FIELDS = ("document_id", "section_id", "section_type", "index")


def _iter_context(path):
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path}: line {lineno}: malformed record: {exc}") from None
            if not isinstance(record, dict) or not isinstance(record.get("node_id"), str):
                raise ValueError(f"{path}: line {lineno}: expected object with str node_id")
            index = record.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError(f"{path}: line {lineno}: index must be an int")
            for key in ("document_id", "section_id"):
                if not isinstance(record.get(key), str):
                    raise ValueError(f"{path}: line {lineno}: {key} must be str")
            yield record


def load_context(path, wanted):
    """Stream the context map twice; return {node_id: {..., "prev", "next"}} for wanted nodes.

    "prev"/"next" are node ids of the neighbours at index -/+ 1 in the same document and section,
    or None. Only wanted nodes and their neighbours' ids are kept.
    """
    context = {}
    for record in _iter_context(path):
        if record["node_id"] in wanted:
            context[record["node_id"]] = {k: record.get(k) for k in _FIELDS}
    slots = {}
    for node_id, rec in context.items():
        for side, offset in (("prev", -1), ("next", 1)):
            rec[side] = None
            slots[(rec["document_id"], rec["section_id"], rec["index"] + offset)] = None
    for record in _iter_context(path):
        key = (record["document_id"], record["section_id"], record["index"])
        if key in slots:
            if slots[key] not in (None, record["node_id"]):
                raise ValueError(f"two nodes at {key!r}")
            slots[key] = record["node_id"]
    for rec in context.values():
        base = (rec["document_id"], rec["section_id"])
        rec["prev"] = slots[base + (rec["index"] - 1,)]
        rec["next"] = slots[base + (rec["index"] + 1,)]
    return context


def section_vocab(rows, context):
    """Sorted section types of the given (train) rows."""
    return sorted({context[row[0]]["section_type"] for row in rows
                   if row[0] in context and isinstance(context[row[0]]["section_type"], str)})


def augment(vectors, context, use_neighbours=True, use_section=True, vocab=()):
    """Return {node_id: augmented vector} for every node in context that has a vector."""
    vocab_index = {t: i for i, t in enumerate(vocab)}
    out = {}
    for node_id, rec in context.items():
        own = vectors.get(node_id)
        if own is None:
            continue
        features = [float(x) for x in own]
        if use_neighbours:
            for side in ("prev", "next"):
                neighbour = vectors.get(rec[side]) if rec[side] is not None else None
                if neighbour is not None and len(neighbour) != len(own):
                    raise ValueError(f"neighbour {rec[side]!r} has dimension {len(neighbour)}")
                if neighbour is None:
                    features.extend([0.0] * len(own))
                else:
                    features.extend(float(x) for x in neighbour)
        if use_section:
            onehot = [0.0] * len(vocab_index)
            if rec["section_type"] in vocab_index:
                onehot[vocab_index[rec["section_type"]]] = 1.0
            features.extend(onehot)
        out[node_id] = features
    return out


def ablate(rows, vectors, context, model="logreg", seed=0, *, use_neighbours=True,
           use_section=True, margin=0.0):
    """rows is a build_training_set split; return baseline vs context held-out macro-F1."""
    train, held = rows["train"], rows["held_out"]
    vocab = section_vocab(train, context) if use_section else []
    augmented = augment(vectors, context, use_neighbours, use_section, vocab)
    variants = {}
    for name, feats in (("baseline", vectors), ("context", augmented)):
        head = make_model(model, seed=seed).fit(train, feats)
        variants[name] = evaluate(head, held, feats)["macro_f1"]
    delta = variants["context"] - variants["baseline"]
    return {"model": model, "seed": seed, "margin": margin,
            "use_neighbours": use_neighbours, "use_section": use_section,
            "section_types": vocab,
            "macro_f1": variants, "delta": delta,
            "verdict": "keep" if delta > margin else "drop",
            "train": {"examples": len(train), "documents": len({r[1] for r in train})},
            "held_out": {"examples": len(held), "documents": len({r[1] for r in held})}}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m analysis.context_features")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--documents", required=True)
    parser.add_argument("--vectors", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--model", choices=sorted(MODELS), default="logreg")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--held-out", type=float, default=0.2)
    parser.add_argument("--margin", type=float, default=0.0)
    parser.add_argument("--neighbours", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--section", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    split = build_training_set(
        CandidateLabelStore(args.labels).iter_candidates(),
        load_document_map(args.documents),
        held_out_fraction=args.held_out, seed=args.seed)
    wanted = {row[0] for row in split["train"]} | {row[0] for row in split["held_out"]}
    context = load_context(args.context, wanted)
    missing = sorted(wanted - context.keys())
    if missing:
        raise SystemExit(f"node {missing[0]!r} has no context record")
    needed = set(wanted)
    if args.neighbours:
        needed |= {rec[s] for rec in context.values() for s in ("prev", "next") if rec[s]}
    vectors = load_vectors(args.vectors, needed)
    report = ablate(split, vectors, context, args.model, args.seed,
                    use_neighbours=args.neighbours, use_section=args.section, margin=args.margin)
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

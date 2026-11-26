"""CO-07: boilerplate and near-duplicate detection over a Markdown corpus (stdlib only).

Streams documents through experiments.corpus.iter_documents and flags, for the expert's review:

* ``repeated``: a normalised passage of at least ``min_words`` whitespace-separated tokens
  (paragraphs and lines of multi-line paragraphs; lowercased, whitespace collapsed, digit runs
  masked as ``#``; shorter passages such as common headings are ignored) occurring
  in at least ``min_docs`` distinct documents (templates, disclaimers, repeated headers/footers).
* ``near_duplicate_docs``: document pairs whose word 5-gram shingle Jaccard similarity, estimated
  by a seeded MinHash (64 permutations) with LSH banding (16 bands x 4 rows), is >= threshold.

Memory bound: document texts are never retained. State is one entry per distinct normalised
passage (8-byte hash -> set of doc ids, sample text capped at 200 chars) plus one 64-integer
MinHash signature per document, i.e. O(min(distinct passages, max_passages) x docs containing
them + 64 x documents). Once the passage table holds ``max_passages`` entries no new passages are
inserted (existing ones still count); ``totals.passage_table_capped`` records whether that happened.
Documents are identified by their POSIX path relative to CORPUS_DIR without suffix (``a/x.md`` ->
``a/x``), so same-stem files in different subdirectories stay distinct.

Output is deterministic: same input -> byte-identical JSON. Production caller is the CLI;
unwired otherwise by design.

CLI: python -m experiments.boilerplate report CORPUS_DIR OUT.json
     [--min-docs N] [--threshold T] [--min-words N] [--max-passages N] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Iterator

from experiments.corpus import iter_documents

NUM_PERM = 64
BANDS = 16
ROWS = NUM_PERM // BANDS
SHINGLE = 5
SEED = 7
TEXT_CAP = 200
_PRIME = (1 << 61) - 1

_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_WORD = re.compile(r"\w+")
_BLANK = re.compile(r"\n[ \t]*\n")

_rng = random.Random(SEED)
_PERMS = [(_rng.randrange(1, _PRIME), _rng.randrange(0, _PRIME)) for _ in range(NUM_PERM)]


def normalize(text: str) -> str:
    """Lowercase, collapse whitespace, mask digit runs as '#'."""
    return _DIGITS.sub("#", _WS.sub(" ", text.lower()).strip())


def _hash(text: str, size: int = 8) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=size).digest(), "big")


def _passages(text: str) -> Iterator[str]:
    """Normalised paragraphs and, for multi-line paragraphs, their individual lines."""
    for para in _BLANK.split(text.replace("\r\n", "\n")):
        norm = normalize(para)
        if norm:
            yield norm
        lines = [ln for ln in para.split("\n") if ln.strip()]
        if len(lines) > 1:
            for line in lines:
                yield normalize(line)


def _signature(text: str) -> tuple[int, ...] | None:
    words = _WORD.findall(text.lower())
    if not words:
        return None
    n = max(1, len(words) - SHINGLE + 1)
    hashes = {_hash(" ".join(words[i:i + SHINGLE])) for i in range(n)}
    return tuple(min((a * h + b) % _PRIME for h in hashes) for a, b in _PERMS)


def build_report(corpus_dir: str | os.PathLike, min_docs: int = 3, threshold: float = 0.8,
                 min_words: int = 4, max_passages: int = 1_000_000) -> dict:
    """Build the flag report; documents are streamed and never retained."""
    passages: dict[int, list] = {}  # hash -> [sample text, set of doc ids]
    signatures: dict[str, tuple[int, ...]] = {}
    stems: set[str] = set()
    capped = False
    root = Path(corpus_dir)
    for document in iter_documents(corpus_dir):
        stem = document.path.relative_to(root).with_suffix("").as_posix()
        stems.add(stem)
        for norm in sorted(set(_passages(document.text))):
            if len(norm.split()) < min_words:
                continue
            key = _hash(norm)
            entry = passages.get(key)
            if entry is None:
                if len(passages) >= max_passages:
                    capped = True
                    continue
                entry = passages[key] = [norm[:TEXT_CAP], set()]
            entry[1].add(stem)
        sig = _signature(document.text)
        if sig is not None:
            signatures[stem] = sig

    flags = []
    for text, docs in passages.values():
        if len(docs) >= min_docs:
            flags.append({"kind": "repeated", "text": text,
                          "documents": sorted(docs), "count": len(docs)})

    buckets: dict[tuple, list[str]] = {}
    for stem in sorted(signatures):
        sig = signatures[stem]
        for band in range(BANDS):
            buckets.setdefault((band,) + sig[band * ROWS:(band + 1) * ROWS], []).append(stem)
    candidates = set()
    for members in buckets.values():
        candidates.update(combinations(members, 2))
    for a, b in candidates:
        sa, sb = signatures[a], signatures[b]
        sim = sum(x == y for x, y in zip(sa, sb)) / NUM_PERM
        if sim >= threshold:
            flags.append({"kind": "near_duplicate_docs", "documents": [a, b],
                          "count": 2, "similarity": round(sim, 4)})

    flags.sort(key=lambda f: (f["kind"], -f["count"], f.get("text", ""), f["documents"]))
    by_kind = {k: sum(f["kind"] == k for f in flags) for k in ("near_duplicate_docs", "repeated")}
    return {
        "params": {"min_docs": min_docs, "threshold": threshold, "min_words": min_words,
                   "max_passages": max_passages, "num_perm": NUM_PERM,
                   "bands": BANDS, "shingle": SHINGLE, "seed": SEED},
        "flags": flags,
        "totals": {"documents": len(stems), "distinct_passages": len(passages),
                   "flags": len(flags), "by_kind": by_kind,
                   "passage_table_capped": capped},
    }


def write_report(report: dict, out: str | os.PathLike, force: bool = False) -> None:
    """Write the report as sorted-key JSON; refuse to overwrite unless force."""
    data = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(out, "w" if force else "x", encoding="utf-8") as fh:
        fh.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.boilerplate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    report = sub.add_parser("report", help="write a JSON boilerplate/near-duplicate flag report")
    report.add_argument("corpus")
    report.add_argument("out")
    report.add_argument("--min-docs", type=int, default=3)
    report.add_argument("--threshold", type=float, default=0.8)
    report.add_argument("--min-words", type=int, default=4)
    report.add_argument("--max-passages", type=int, default=1_000_000)
    report.add_argument("--force", action="store_true", help="overwrite an existing OUT")
    args = parser.parse_args(argv)
    if not Path(args.corpus).is_dir():
        print(f"error: corpus directory not found: {args.corpus}", file=sys.stderr)
        return 2
    if Path(args.out).exists() and not args.force:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 1
    try:
        result = build_report(args.corpus, min_docs=args.min_docs, threshold=args.threshold,
                              min_words=args.min_words, max_passages=args.max_passages)
        write_report(result, args.out, force=args.force)
    except FileExistsError:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

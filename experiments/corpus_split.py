"""CO-08: fixed, versioned train/dev/test split by document.

Builds a three-way split of CO-06 metadata doc_ids, writes it as a JSON
manifest, verifies it, and adapts it to experiments.splits.DocumentSplit.
Stdlib only and offline. Unwired by design: G-01.5, AN-02 and the G-02 runner
will load the manifest. Memory is O(number of doc ids); metadata is streamed
and only ids are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from pathlib import Path

from experiments.corpus_metadata import MetadataError, iter_records, validate_file
from experiments.splits import DocumentSplit

FORMAT_VERSION = 1
SPLIT_NAMES = ("train", "dev", "test")
_KEYS = {"version", "seed", "fractions", "splits", "sha256"}


class SplitError(ValueError):
    """Invalid input, fractions or manifest."""


def splits_hash(splits: dict) -> str:
    """SHA-256 over canonical JSON of the split lists."""
    canon = json.dumps(splits, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _check_fractions(dev: object, test: object) -> None:
    for name, f in (("dev", dev), ("test", test)):
        if isinstance(f, bool) or not isinstance(f, (int, float)) or not math.isfinite(f) or f <= 0:
            raise SplitError(f"{name} fraction must be a number > 0, got {f!r}")
    if dev + test >= 1:  # type: ignore[operator]
        raise SplitError(f"dev + test fractions must be < 1, got {dev + test!r}")  # type: ignore[operator]


def read_doc_ids(metadata: str | os.PathLike) -> list[str]:
    """Return doc_ids of a valid metadata file; refuse invalid files and duplicates."""
    errors = validate_file(metadata)
    if errors:
        raise SplitError("invalid metadata:\n" + "\n".join(str(e) for e in errors))
    seen: set[str] = set()
    for lineno, record in enumerate(iter_records(metadata), start=1):
        doc_id = record["doc_id"]
        if doc_id in seen:
            raise SplitError(f"{metadata}: duplicate doc_id {doc_id!r} (record {lineno})")
        seen.add(doc_id)
    return sorted(seen)


def build_split(metadata: str | os.PathLike, seed: int, dev: float, test: float) -> dict:
    """Build a manifest; assignment depends only on the id set and seed.

    Counts are floor(n * fraction) with a minimum of one for dev and test;
    train must keep at least one document.
    """
    _check_fractions(dev, test)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SplitError(f"seed must be an integer, got {seed!r}")
    ids = read_doc_ids(metadata)
    n = len(ids)
    n_test = max(1, int(n * test))
    n_dev = max(1, int(n * dev))
    if n_test + n_dev >= n:
        raise SplitError(f"too few documents ({n}) for nonempty train, dev and test splits")
    random.Random(seed).shuffle(ids)
    splits = {
        "train": sorted(ids[n_test + n_dev:]),
        "dev": sorted(ids[n_test:n_test + n_dev]),
        "test": sorted(ids[:n_test]),
    }
    return {
        "version": FORMAT_VERSION,
        "seed": seed,
        "fractions": {"dev": dev, "test": test},
        "splits": splits,
        "sha256": splits_hash(splits),
    }


def verify_manifest(manifest: object, metadata: str | os.PathLike | None = None) -> list[str]:
    """Return field-specific errors; empty means valid."""
    if not isinstance(manifest, dict):
        return ["manifest: must be a JSON object"]
    errors = [f"{k}: missing field" for k in sorted(_KEYS - manifest.keys())]
    errors += [f"{k}: unknown field" for k in sorted(manifest.keys() - _KEYS)]
    if "version" in manifest and manifest["version"] != FORMAT_VERSION:
        errors.append(f"version: expected {FORMAT_VERSION}, got {manifest['version']!r}")
    seed = manifest.get("seed")
    if "seed" in manifest and (isinstance(seed, bool) or not isinstance(seed, int)):
        errors.append("seed: must be an integer")
    fr = manifest.get("fractions")
    if "fractions" in manifest:
        if not isinstance(fr, dict) or set(fr) != {"dev", "test"}:
            errors.append("fractions: must be an object with exactly dev and test")
        else:
            try:
                _check_fractions(fr["dev"], fr["test"])
            except SplitError as e:
                errors.append(f"fractions: {e}")
    splits = manifest.get("splits")
    owner: dict[str, str] = {}
    lists_ok = False
    if "splits" in manifest:
        if not isinstance(splits, dict) or set(splits) != set(SPLIT_NAMES):
            errors.append("splits: must be an object with exactly train, dev and test")
        else:
            lists_ok = True
            for name in SPLIT_NAMES:
                ids = splits[name]
                if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
                    errors.append(f"splits.{name}: must be a list of nonempty strings")
                    lists_ok = False
                    continue
                if not ids:
                    errors.append(f"splits.{name}: must not be empty")
                if ids != sorted(set(ids)):
                    errors.append(f"splits.{name}: must be sorted without duplicates")
                for i in ids:
                    if i in owner and owner[i] != name:
                        errors.append(f"splits.{name}: {i!r} appears in more than one split ({owner[i]})")
                    owner.setdefault(i, name)
            if lists_ok and manifest.get("sha256") != splits_hash(splits):
                errors.append("sha256: does not match splits content")
    if metadata is not None and lists_ok:
        try:
            meta_ids = set(read_doc_ids(metadata))
        except (SplitError, MetadataError, OSError) as e:
            errors.append(f"metadata: {e}")
        else:
            for i in sorted(meta_ids - owner.keys()):
                errors.append(f"metadata: doc_id {i!r} not in any split")
            for i in sorted(owner.keys() - meta_ids):
                errors.append(f"splits.{owner[i]}: {i!r} unknown (not in metadata)")
    return errors


def write_manifest(manifest: dict, out: str | os.PathLike, force: bool = False) -> None:
    """Write manifest JSON; refuse to overwrite unless force."""
    data = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(out, "w" if force else "x", encoding="utf-8") as fh:
        fh.write(data)


def load_manifest(path: str | os.PathLike) -> dict:
    """Load and verify a manifest; raise SplitError if invalid."""
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SplitError(f"{path}: cannot read manifest: {e}") from e
    errors = verify_manifest(manifest)
    if errors:
        raise SplitError(f"{path}: invalid manifest:\n" + "\n".join(errors))
    return manifest


def to_document_split(manifest: dict, eval_split: str = "test") -> DocumentSplit:
    """DocumentSplit with train ids as train and eval_split ("test"|"dev") as test."""
    if eval_split not in ("test", "dev"):
        raise ValueError(f"eval_split must be 'test' or 'dev', got {eval_split!r}")
    errors = verify_manifest(manifest)
    if errors:
        raise SplitError("invalid manifest:\n" + "\n".join(errors))
    return DocumentSplit(manifest["splits"]["train"], manifest["splits"][eval_split])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.corpus_split")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a split manifest from CO-06 metadata")
    b.add_argument("metadata")
    b.add_argument("out")
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--dev", type=float, required=True)
    b.add_argument("--test", type=float, required=True)
    b.add_argument("--force", action="store_true", help="overwrite an existing OUT")
    c = sub.add_parser("check", help="verify a split manifest")
    c.add_argument("manifest")
    c.add_argument("--metadata", default=None)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "build":
            if Path(args.out).exists() and not args.force:
                print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
                return 1
            manifest = build_split(args.metadata, args.seed, args.dev, args.test)
            write_manifest(manifest, args.out, force=args.force)
            return 0
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        errors = verify_manifest(manifest, args.metadata)
    except FileExistsError:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 1
    except (SplitError, MetadataError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for e in errors:
        print(f"{args.manifest}: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

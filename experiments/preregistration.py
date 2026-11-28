"""Read gate threshold records; production caller: runner.run_gate (ST-01)."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile

DEFAULT_ROOT = Path(__file__).with_name("preregistration")
GATE_ID = re.compile(r"[A-Za-z0-9_-]+")


class PreregistrationError(ValueError):
    """A gate has no valid, confirmed threshold record."""


def load(gate: str, root=DEFAULT_ROOT) -> dict:
    """Load and validate a confirmed record from ``root/<gate>.json``."""
    if not isinstance(gate, str) or not GATE_ID.fullmatch(gate):
        raise PreregistrationError("invalid gate id")
    path = Path(root) / f"{gate}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PreregistrationError(f"{gate}: cannot read valid JSON at {path}") from error
    if not isinstance(record, dict):
        raise PreregistrationError(f"{gate}: record must be an object")
    for field in ("gate", "threshold", "metric", "confirmed_by", "confirmed_at"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise PreregistrationError(f"{gate}: {field} must be nonempty text")
    if record["gate"] != gate:
        raise PreregistrationError(f"{gate}: record gate id does not match")
    timestamp = record["confirmed_at"]
    try:
        if "T" not in timestamp:
            raise ValueError("date-time required")
        confirmed_at = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if confirmed_at.utcoffset() != datetime.timedelta(0):
            raise ValueError("UTC required")
    except ValueError as error:
        raise PreregistrationError(f"{gate}: confirmed_at must be ISO 8601 UTC") from error
    if "recorded_commit" in record and (
        not isinstance(record["recorded_commit"], str) or not record["recorded_commit"].strip()
    ):
        raise PreregistrationError(f"{gate}: recorded_commit must be nonempty text if present")
    return record


def require_confirmed(gate: str, root=DEFAULT_ROOT) -> dict:
    """Refuse execution unless the gate has a valid confirmed record."""
    return load(gate, root=root)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must be nonempty text")
    return value


def _gate_id(value: str) -> str:
    if not GATE_ID.fullmatch(value):
        raise argparse.ArgumentTypeError("gate id must use letters, digits, _ or -")
    return value


def main(argv=None) -> int:
    """CLI entrypoint; production caller: the expert at run-sheet step 0.2."""
    parser = argparse.ArgumentParser(
        prog="python -m experiments.preregistration",
        description="Write a gate preregistration record. Only the expert may run this; "
        "agents must not create confirmations (architecture section 6).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    confirm = sub.add_parser(
        "confirm",
        help="write ROOT/GATE.json (expert only)",
        description="Write ROOT/GATE.json confirming a threshold. Only the expert may run "
        "this; once written the threshold is fixed and the file is never overwritten.",
    )
    confirm.add_argument("gate", type=_gate_id, help="gate id, also the file name, e.g. g01")
    confirm.add_argument("--threshold", required=True, type=_nonblank)
    confirm.add_argument("--metric", required=True, type=_nonblank)
    confirm.add_argument("--confirmed-by", required=True, type=_nonblank,
                         help="the expert's identity (no default)")
    confirm.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                         help="record directory (default: experiments/preregistration)")
    confirm.add_argument("--recorded-commit", type=_nonblank, help="optional commit reference")
    args = parser.parse_args(argv)

    root = Path(args.root)
    path = root / f"{args.gate}.json"
    refusal = f"refusing to overwrite {path}: thresholds are fixed once confirmed"
    if os.path.lexists(path):
        print(refusal, file=sys.stderr)
        return 1
    record = {
        "gate": args.gate,
        "threshold": args.threshold,
        "metric": args.metric,
        "confirmed_by": args.confirmed_by,
        "confirmed_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if args.recorded_commit is not None:
        record["recorded_commit"] = args.recorded_commit
    tmp = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=root, prefix=f".{args.gate}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, 0o644)
        os.link(tmp, path)  # fails if path exists in any form, never overwrites
    except FileExistsError:
        print(refusal, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"cannot write {path}: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmp is not None and os.path.lexists(tmp):
            os.unlink(tmp)
    load(args.gate, root)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

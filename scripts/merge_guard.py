#!/usr/bin/env python3
"""Merge one reviewed PR under the standing delegation D-002 (docs/decisions.md).

Usage: python3 scripts/merge_guard.py PR --head FULL_REVIEWED_SHA

The only merge path for planners: raw `gh pr merge` stays denied in .claude/settings.json.
It merges only when the PR is open, not a draft, mergeable, targets the default branch, still
has exactly the reviewed head, and touches no operator-owned path. GitHub re-checks the head
at merge time (--match-head-commit), and the merge is confirmed by re-reading the PR.
Review and the gate are the planner's /review-round and /merge-round duties; this script cannot
see them, nor whether a PR decides an [H] item.
"""

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
# D-002: these stay the operator's to merge.
OPERATOR_PATHS = (
    "docs/decisions.md",
    "docs/architecture.md",
    ".agent/config.toml",
    ".claude/*",
    "scripts/merge_guard.py",
    "experiments/results/G-*",  # a gate result is how a gate becomes `passed`
)
Run = Callable[[Sequence[str]], tuple[int, str]]


def _run(cmd: Sequence[str]) -> tuple[int, str]:
    done = subprocess.run(list(cmd), capture_output=True, text=True, timeout=120, cwd=ROOT)
    return done.returncode, (done.stdout + done.stderr).strip()


def default_branch() -> str:
    try:
        with (ROOT / ".agent" / "config.toml").open("rb") as fh:
            return tomllib.load(fh).get("project", {}).get("default_branch", "main")
    except OSError:
        return "main"


def view(pr: int, run: Run) -> dict:
    fields = "state,isDraft,mergeable,headRefOid,baseRefName,files"
    rc, out = run(["gh", "pr", "view", str(pr), "--json", fields])
    if rc:
        raise RuntimeError(f"gh pr view {pr} failed: {out[:300]}")
    return json.loads(out)


def problems(record: dict, head: str, branch: str) -> list[str]:
    found = []
    if record.get("state") != "OPEN":
        found.append(f"state is {record.get('state')}, not OPEN")
    if record.get("isDraft"):
        found.append("PR is a draft")
    if record.get("mergeable") != "MERGEABLE":
        found.append(f"mergeable is {record.get('mergeable')}")
    if record.get("baseRefName") != branch:
        found.append(f"base is {record.get('baseRefName')}, not {branch}")
    if record.get("headRefOid") != head:
        found.append(f"head is {record.get('headRefOid')}, not the reviewed {head}")
    owned = sorted(
        f["path"]
        for f in record.get("files") or []
        if any(fnmatch.fnmatch(f["path"], pattern) for pattern in OPERATOR_PATHS)
    )
    if owned:
        found.append("operator-owned paths (D-002), leave to the operator: " + ", ".join(owned))
    return found


def guard(pr: int, head: str, *, run: Run = _run, branch: str | None = None) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        print("refusing: --head must be the full 40-character reviewed SHA", file=sys.stderr)
        return 2
    branch = branch or default_branch()
    found = problems(view(pr, run), head, branch)
    if found:
        for problem in found:
            print(f"refusing PR #{pr}: {problem}", file=sys.stderr)
        return 1
    rc, out = run(["gh", "pr", "merge", str(pr), "--merge", "--match-head-commit", head])
    if rc:
        print(f"gh pr merge {pr} failed: {out[:300]}", file=sys.stderr)
        return 1
    state = view(pr, run).get("state")
    if state != "MERGED":
        print(f"PR #{pr} state is {state} after merge; not merged", file=sys.stderr)
        return 1
    print(f"merged PR #{pr} at reviewed head {head}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pr", type=int)
    parser.add_argument("--head", required=True, help="full reviewed head SHA")
    args = parser.parse_args(argv)
    return guard(args.pr, args.head)


if __name__ == "__main__":
    sys.exit(main())

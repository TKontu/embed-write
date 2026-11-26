#!/usr/bin/env python3
"""Provision a fresh lane worktree so it can run the full gate (WF-LANEPROV).

Usage: python3 scripts/lane_provision.py <worktree> [--source <checkout>]

Creates <worktree>/<dir>/node_modules as a symlink to <source>/<dir>/node_modules for each dir in
LINKED (editor, docmodel: the ingest roundtrip gate runs docmodel's node script). The source
defaults to the repo's main worktree (first entry of `git worktree list --porcelain`). Never
copies, installs or deletes anything; runtime stays offline.

Exit codes: 0 link created or already correct; 1 an existing real entry or wrong-target link was
left untouched; 2 the source node_modules is missing (or the source cannot be resolved).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

LINKED = (Path("editor") / "node_modules", Path("docmodel") / "node_modules")


def main_worktree(worktree: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):])
    return None


def provision(worktree: Path, source: Path | None = None) -> tuple[int, str]:
    """Check every link first; create nothing unless all sources exist. Worst code wins."""
    worktree = worktree.resolve()
    if source is None:
        source = main_worktree(worktree)
        if source is None:
            return 2, f"cannot resolve main worktree for {worktree}; pass --source"
    missing = [str(source.resolve() / r) for r in LINKED if not (source.resolve() / r).is_dir()]
    if missing:
        return 2, f"source {', '.join(missing)} missing; install in the source checkout first"
    results = [_link_one(worktree, source.resolve(), r) for r in LINKED]
    return max(c for c, _ in results), "\n".join(m for _, m in results)


def _link_one(worktree: Path, source: Path, rel: Path) -> tuple[int, str]:
    target = source / rel
    link = worktree / rel
    if link.is_symlink():
        current = os.readlink(link)
        if Path(current) == target or link.resolve() == target.resolve():
            return 0, f"ok: {link} -> {current} (already provisioned)"
        return 1, f"refused: {link} links to {current}, not {target}; left untouched"
    if link.exists():
        return 1, f"refused: {link} exists and is not a symlink; left untouched"
    if not link.parent.is_dir():
        return 2, f"{link.parent} missing; is {worktree} a checkout of this repo?"
    link.symlink_to(target, target_is_directory=True)
    return 0, f"created: {link} -> {target}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("worktree", type=Path)
    ap.add_argument("--source", type=Path, default=None)
    args = ap.parse_args(argv)
    code, msg = provision(args.worktree, args.source)
    print(msg, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())

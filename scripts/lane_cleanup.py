#!/usr/bin/env python3
"""Drop finished lanes' worktrees and close their Herdr tabs, by rule (pattern from iknosreview).

Usage: python3 scripts/lane_cleanup.py [--go]     (a dry run unless --go)

Worktrees: a registered worktree outside the main checkout, at a sibling path
(<repo>-lanes/..., <repo>-wt-..., <repo>-r9-a1), is removed with `git worktree remove` (never
--force) once the newest PR on its branch is MERGED or CLOSED and no PR on it is OPEN. Anything
uncertain is held and reported, never forced: `no-pr`, `open-pr`, `dirty`, `unpushed`
(commits on no remote), `busy` (a process has its cwd inside), `carried` (HANDOFF.md names it).

Tabs: a tab labelled <lane prefix><lane> is closed with `herdr tab close <id>` only when its
worktree is gone (or was removed in this run), every pane is idle, done or unknown, it is not carried, and
its label does not mark a planner, loop, supervisor, manager or review server. A tab whose pane is
in the main checkout or outside the lane paths is held as `foreign`.

/merge-round runs this after its merges, /reconcile before handoff.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = re.compile(r"round[-_ ]?loop|review[-_ ]?server|planner|supervisor|manager", re.I)
DELETED = " (deleted)"
SETTLED = {"idle", "done", "unknown", None}  # any other pane state keeps the tab
Run = Callable[[Sequence[str]], tuple[int, str]]


def _run(cmd: Sequence[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(list(cmd), capture_output=True, text=True, timeout=120, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, done.stdout.strip() or done.stderr.strip()


def _busy() -> list[str]:
    """Every live process's cwd, except this process's own."""
    cwds = []
    for proc in Path("/proc").glob("[0-9]*"):
        if proc.name == str(os.getpid()):
            continue
        try:
            cwds.append(os.readlink(proc / "cwd"))
        except OSError:
            continue
    return cwds


def lane_prefix(root: Path = ROOT) -> str:
    """Same naming rule as round_supervisor.repo_names: live-<slug>-."""
    try:
        with (root / ".agent" / "config.toml").open("rb") as fh:
            raw = tomllib.load(fh).get("supervisor", {}).get("name")
    except OSError:
        raw = None
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw or root.name).lower()).strip("-") or "repo"
    return f"live-{slug}-"


def carried_lines(handoff: str) -> list[str]:
    """Lines of HANDOFF.md that carry a lane: under a heading about carried lanes, or saying so."""
    lines, in_section = [], False
    for line in handoff.splitlines():
        if line.startswith("#"):
            in_section = bool(re.search(r"carr", line, re.I))
            continue
        if re.search(r"\bno carried\b", line, re.I):
            continue
        if in_section or re.search(r"carr(y|ies|ied)", line, re.I):
            lines.append(line)
    return lines


def _is_carried(names: Iterable[str], carried: list[str]) -> bool:
    return any(
        re.search(rf"(?<![\w/-]){re.escape(n)}(?![\w-])", line) for n in names if n for line in carried
    )


def worktrees(run: Run) -> dict[str, str]:
    rc, out = run(["git", "worktree", "list", "--porcelain"])
    if rc:
        raise RuntimeError(f"git worktree list failed: {out[:200]}")
    trees, path = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ")
            trees[path] = ""
        elif line.startswith("branch ") and path:
            trees[path] = line.removeprefix("branch refs/heads/")
    return trees


def _is_lane_path(path: str, root: Path) -> bool:
    return path != str(root) and path.startswith(str(root) + "-")


def _inside(path: str, cwds: Iterable[str]) -> bool:
    return any(c == path or c.startswith(path + "/") for c in cwds)


def tree_hold(path: str, branch: str, run: Run) -> str | None:
    """Why this lane worktree must stay (busy aside), or None when its work is finished."""
    if not branch:
        return "detached"
    rc, out = run(["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "state"])
    if rc:
        return "unreachable"
    states = [pr["state"] for pr in json.loads(out or "[]")]
    if not states:
        return "no-pr"
    if "OPEN" in states:
        return "open-pr"
    rc, out = run(["git", "-C", path, "status", "--porcelain"])
    if rc or out:
        return "dirty"
    rc, out = run(["git", "-C", path, "rev-list", "HEAD", "--not", "--remotes"])
    if rc or out:
        return "unpushed"
    return None


def cleanup(
    *,
    root: Path = ROOT,
    prefix: str | None = None,
    go: bool = False,
    handoff: str | None = None,
    run: Run = _run,
    busy: Callable[[], list[str]] = _busy,
    settle: float = 2.0,
) -> list[str]:
    """Tabs first, so a finished lane's idle shell no longer pins its worktree; then worktrees."""
    prefix = prefix or lane_prefix(root)
    if handoff is None:
        hp = root / "HANDOFF.md"
        handoff = hp.read_text(encoding="utf-8") if hp.is_file() else ""
    carried = carried_lines(handoff)
    report: list[str] = []
    trees = worktrees(run)

    holds: dict[str, str | None] = {}
    for path, branch in sorted(trees.items()):
        if _is_lane_path(path, root):
            carry = _is_carried([path, Path(path).name], carried)
            holds[path] = "carried" if carry else tree_hold(path, branch, run)

    rc, out = run(["herdr", "tab", "list"])
    tabs = json.loads(out)["result"]["tabs"] if not rc else []
    if rc:
        report.append(f"tabs skipped: herdr tab list failed: {out[:160]}")
    rc, out = run(["herdr", "pane", "list"])
    panes = json.loads(out)["result"]["panes"] if not rc else []
    freed: set[str] = set()  # paths whose tab shell this run closes
    for meta in tabs:
        label, tab_id = str(meta.get("label", "")), meta["tab_id"]
        if not label.startswith(prefix) or PROTECTED.search(label):
            continue
        mine = [p for p in panes if p.get("tab_id") == tab_id]
        raw = [str(p.get("cwd") or "") for p in mine]
        paths = {c.removesuffix(DELETED) for c in raw}
        statuses = {p.get("agent_status") for p in mine}
        if statuses - SETTLED:
            hold = "active: " + ",".join(sorted(str(x) for x in statuses - SETTLED))
        elif _is_carried([label, *paths], carried):
            hold = "carried"
        elif not paths or not all(
            _is_lane_path(c.removesuffix(DELETED), root) and (c.endswith(DELETED) or c in trees)
            for c in raw
        ):
            hold = "foreign"  # only a registered lane worktree, or one already deleted
        elif any(p in trees and holds.get(p) for p in paths):
            hold = "worktree-kept"
        else:
            hold = None
        if hold:
            report.append(f"hold tab {tab_id} {label}: {hold}")
        elif not go:
            report.append(f"would close tab {tab_id} {label}")
            freed |= paths
        else:
            rc, out = run(["herdr", "tab", "close", tab_id])
            if rc:
                report.append(f"hold tab {tab_id} {label}: close failed: {out[:160]}")
            else:
                report.append(f"closed tab {tab_id} {label}")
                freed |= paths

    if go and freed and settle:
        time.sleep(settle)  # let the closed tabs' shells exit
    cwds = busy()  # re-read: closing a tab ends its shell
    if not go:  # a dry run cannot close tabs, so it assumes their shells go
        cwds = [c for c in cwds if not any(c == f or c.startswith(f + "/") for f in freed)]
    removed = False
    for path, hold in holds.items():
        branch = trees[path] or "detached"
        hold = hold or ("busy" if _inside(path, cwds) else None)
        if hold:
            report.append(f"hold {path} ({branch}): {hold}")
        elif not go:
            report.append(f"would remove {path} ({branch})")
        else:
            rc, out = run(["git", "worktree", "remove", path])
            if rc:
                report.append(f"hold {path} ({branch}): remove failed: {out[:160]}")
            else:
                report.append(f"removed {path} ({branch})")
                removed = True
    if removed:
        run(["git", "worktree", "prune"])
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--go", action="store_true", help="act; without it, a dry run")
    args = parser.parse_args(argv)
    for line in cleanup(go=args.go):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

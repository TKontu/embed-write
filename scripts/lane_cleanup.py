#!/usr/bin/env python3
"""Drop finished lanes' worktrees and close their Herdr tabs, by rule (pattern from iknosreview).

Usage: python3 scripts/lane_cleanup.py [--go] [--all-rounds] [--sweep]   (a dry run unless --go)
       python3 scripts/lane_cleanup.py --preflight   (exit 1 while a closed round has leftovers)

Every round's lanes are in scope (--all-rounds is the default and is accepted for parity with
iknosreview). The round ledger (.agent-runs/R*/round.json, kept by scripts/round.py) maps a tab by its
label <lane prefix>r<N>-a<M> and a worktree by its branch (or a r<N>-a<M> path name) to round R<N>,
lane A<M>.

Worktrees: a registered worktree outside the main checkout, at a sibling path
(<repo>-lanes/..., <repo>-wt-..., <repo>-r9-a1), or exactly one level inside the main checkout's
top-level worktrees/ directory (<repo>/worktrees/r9-a1), is removed with `git worktree remove` (never
--force) once the newest PR on its branch is MERGED or CLOSED and no PR on it is OPEN. Anything
uncertain is held and reported, never forced: `no-pr`, `open-pr`, `dirty`, `unpushed`
(commits on no remote), `busy` (a process has its cwd inside), `carried` (HANDOFF.md names it).
The one tolerated untracked entry is a `node_modules` symlink at any depth (e.g. editor/node_modules):
it does not make a tree `dirty`, and under --go the link itself (never its target) is unlinked right
before `git worktree remove`. A real node_modules directory, any other untracked file or any
tracked change still holds the tree as `dirty`; a dry run unlinks nothing.
A directory at a lane path that is not a registered worktree and holds none (e.g. left by a remove
killed at its timeout) is reported as `orphan <path>: unregistered directory, not removed`; it is
never deleted or modified, in a dry run or under --go.

Closed rounds: a lane worktree whose round the ledger shows closed is also removed when its branch
has no PR at all, provided it is clean and has no unpushed commits; dirty or unpushed trees are held
and reported with their round and lane (`hold <path> (<branch>) R5/A1: dirty`).

Tabs: a tab whose label maps to a ledger lane is closed when that lane is merged or cancelled or
its round is closed, every pane is idle, done or unknown, it is not carried and its label is not
protected, whatever its pane's cwd (planners often start lanes from the main checkout). An
unresolved lane of an open round is held as `lane R7/A1 <state>`. Otherwise a tab labelled <lane prefix><lane> is closed with `herdr tab close <id>` only when its
worktree is gone (or was removed in this run), every pane is idle, done or unknown, it is not carried, and
its label does not mark a planner, loop, supervisor, manager or review server. A tab whose pane is
in the main checkout or outside the lane paths (e.g. <repo>/.claude/worktrees/...) is held as `foreign`.

--sweep also covers Claude agent worktrees (<repo>/.claude/worktrees/<name>, same rules) and prunes
branches: a local branch whose PR is merged or closed (no OPEN PR), that no worktree has checked
out, is not the default branch or the base of an open PR, not an unresolved lane of an open round,
not carried, and whose tip is contained in a PR head (else `newer-than-pr`), is deleted with
`git branch -D`. Origin is first refreshed with `git fetch --prune origin`; such a branch there is
deleted in batches of 50 per push, each leased to the tip inspected (--force-with-lease), so commits
pushed later survive; "remote ref does not exist" counts as already deleted and its tracking ref is
dropped. Both only under --go. A ledger-mapped tab whose lane worktree still exists and is held stays
open (`worktree-kept`), even in a closed round.

--preflight runs the --sweep dry run and lists what a closed round still has to remove (tabs,
worktrees, branches) that --go would actually act on: busy trees and items the last --go run failed
on (.agent-runs/lane-cleanup-failed.json) do not count; it fails closed when herdr or gh cannot
answer. `round.py init` runs it.

/merge-round runs `--go --sweep` after its merges, /reconcile before handoff; a summary of counts by
action and reason ends the report.
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
Run = Callable[..., tuple[int, str]]  # run(cmd, timeout=None) -> (returncode, output)
TIMED_OUT = "timed out after "
REMOVE_TIMEOUT = 600  # a lane with a large .venv can take minutes to remove


def _run(cmd: Sequence[str], timeout: float | None = None) -> tuple[int, str]:
    limit = 120 if timeout is None else timeout
    try:
        done = subprocess.run(list(cmd), capture_output=True, text=True, timeout=limit, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return 1, f"{TIMED_OUT}{limit:g}s"
    except OSError as exc:
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
            section = tomllib.load(fh).get("supervisor", {})
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        section = {}
    # A non-table `supervisor = "x"` is treated as empty, as in round_supervisor.
    raw = section.get("name") if isinstance(section, dict) else None
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
    """A sibling path (<root>-...) or exactly <root>/worktrees/<name>; never root or other inside paths."""
    if path.startswith(str(root) + "-"):
        return True
    rel = path.removeprefix(str(root) + "/worktrees/")
    return rel != path and rel not in ("", ".", "..") and "/" not in rel


LANE_NAME = re.compile(r"r\d+-[a-z]+\d*")  # round lane names such as r221-a1; never -lanes, -results


def orphan_dirs(root: Path, trees: Iterable[str]) -> list[str]:
    """Directories at lane paths that are not registered worktrees and hold none (report only).

    Scans one listing each of root.parent (<root>-... siblings) and root/worktrees. A container such
    as <root>-lanes that holds a registered worktree is not an orphan. Nothing is ever modified.
    """
    registered = set(trees)
    found = []
    for base in (root.parent, root / "worktrees"):
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            path = str(entry)
            if not _is_lane_path(path, root) or entry.is_symlink() or not entry.is_dir():
                continue
            if base == root.parent and not LANE_NAME.fullmatch(path.removeprefix(str(root) + "-")):
                continue  # containers and other siblings are not lanes
            if path in registered or any(t.startswith(path + "/") for t in registered):
                continue
            found.append(path)
    return found


def _inside(path: str, cwds: Iterable[str]) -> bool:
    return any(c == path or c.startswith(path + "/") for c in cwds)


def node_modules_links(path: str, status: str) -> list[Path] | None:
    """The untracked node_modules symlinks that are a tree's only status entries, else None."""
    links = []
    for line in status.splitlines():
        rel = line[3:]
        if not line.startswith("?? ") or rel.startswith('"') or Path(rel).name != "node_modules":
            return None
        link = Path(path) / rel
        if not link.is_symlink():
            return None
        links.append(link)
    return links


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
    if rc or node_modules_links(path, out) is None:
        return "dirty"
    rc, out = run(["git", "-C", path, "rev-list", "HEAD", "--not", "--remotes"])
    if rc or out:
        return "unpushed"
    return None


RESOLVED = {"merged", "cancelled"}
LABEL_LANE = re.compile(r"r(\d+)-a(\d+)")
PATH_LANE = re.compile(r"(?:^|-)r(\d+)-a(\d+)$")
Ledger = dict[str, dict]


def load_ledger(root: Path = ROOT) -> Ledger:
    """{round id: manifest} from .agent-runs/*/round.json; unreadable or id-less records are skipped."""
    found: Ledger = {}
    for record in sorted((root / ".agent-runs").glob("*/round.json")):
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("id") == record.parent.name:
            found[record.parent.name] = data
    return found


def _lane(ledger: Ledger, rid: str, aid: str) -> tuple[str, str] | None:
    """(round state, lane state or "") for a known round, else None."""
    manifest = ledger.get(rid)
    if manifest is None:
        return None
    lane = (manifest.get("assignments") or {}).get(aid) or {}
    return str(manifest.get("state")), str(lane.get("state") or "")


def _finished(state: tuple[str, str]) -> bool:
    return state[0] == "closed" or state[1] in RESOLVED


def _branch_lanes(ledger: Ledger) -> dict[str, tuple[str, str]]:
    """branch -> (round, lane); the newest round wins when a branch was reassigned."""
    lanes: dict[str, tuple[str, str]] = {}
    for rid in sorted(ledger, key=lambda r: int(r[1:]) if r[1:].isdigit() else -1):
        for aid, a in (ledger[rid].get("assignments") or {}).items():
            if isinstance(a, dict) and a.get("branch"):
                lanes[str(a["branch"])] = (rid, aid)
    return lanes


def _tree_lane(ledger: Ledger, by_branch: dict, path: str, branch: str) -> tuple[str, str] | None:
    if branch in by_branch:
        return by_branch[branch]
    m = PATH_LANE.search(Path(path).name)
    if m and _lane(ledger, f"R{m[1]}", f"A{m[2]}") is not None:
        return f"R{m[1]}", f"A{m[2]}"
    return None


def _is_agent_path(path: str, root: Path) -> bool:
    rel = path.removeprefix(str(root) + "/.claude/worktrees/")
    return rel != path and rel not in ("", ".", "..") and "/" not in rel


def closed_round_hold(path: str, branch: str, run: Run) -> str | None:
    """tree_hold for a closed round's lane: a PR-less tree goes too when clean and pushed."""
    hold = tree_hold(path, branch, run)
    if hold != "no-pr":
        return hold
    rc, out = run(["git", "-C", path, "status", "--porcelain"])
    if rc or node_modules_links(path, out) is None:
        return "dirty"
    rc, out = run(["git", "-C", path, "rev-list", "HEAD", "--not", "--remotes"])
    return "unpushed" if rc or out else None


def summary(lines: Iterable[str]) -> list[str]:
    """Counts by action and reason, e.g. `summary: hold dirty=2`."""
    counts: dict[str, int] = {}
    for line in lines:
        if line.startswith("summary: "):
            continue
        kind = "tab " if "tab" in line.split(" ")[1:3] else ""
        kind = "remote branch " if " remote branch " in line else kind
        kind = "branch " if not kind and re.match(r"\S+( \S+)? branch ", line) else kind
        if line.startswith("hold"):
            reason = line.rsplit(": ", 1)[-1].split(":")[0].strip()
            key = f"hold {kind}{reason}"
        elif ": " in line and line.startswith(("tabs skipped", "branches skipped")):
            key = line.split(":")[0]
        else:
            words = line.split(" ")
            verb = " ".join(words[:2]) if words[0] == "would" else words[0]
            key = f"{verb} {kind}".strip() if kind else verb
        counts[key] = counts.get(key, 0) + 1
    return [f"summary: {k}={v}" for k, v in sorted(counts.items())]


def _items(
    *,
    root: Path,
    prefix: str | None,
    go: bool,
    handoff: str | None,
    run: Run,
    busy: Callable[[], list[str]],
    settle: float,
    ledger: Ledger | None,
    sweep: bool,
    state: Path | None = None,
) -> list[tuple[str, str | None]]:
    """(report line, closed round it belongs to or None). Tabs first, then worktrees, branches."""
    prefix = prefix or lane_prefix(root)
    if handoff is None:
        hp = root / "HANDOFF.md"
        handoff = hp.read_text(encoding="utf-8") if hp.is_file() else ""
    ledger = load_ledger(root) if ledger is None else ledger
    by_branch = _branch_lanes(ledger)
    carried = carried_lines(handoff)
    report: list[tuple[str, str | None]] = []

    def closed(rid: str | None) -> str | None:
        return rid if rid and (ledger.get(rid) or {}).get("state") == "closed" else None

    trees = worktrees(run)

    holds: dict[str, str | None] = {}
    tree_lanes: dict[str, tuple[str, str] | None] = {}
    for path, branch in sorted(trees.items()):
        if _is_lane_path(path, root) or (sweep and _is_agent_path(path, root)):
            lane = _tree_lane(ledger, by_branch, path, branch)
            tree_lanes[path] = lane
            if _is_carried([path, Path(path).name], carried):
                holds[path] = "carried"
            elif lane and ledger[lane[0]].get("state") == "closed":
                holds[path] = closed_round_hold(path, branch, run)
            else:
                holds[path] = tree_hold(path, branch, run)

    rc, out = run(["herdr", "tab", "list"])
    tabs = json.loads(out)["result"]["tabs"] if not rc else []
    if rc:
        report.append((f"tabs skipped: herdr tab list failed: {out[:160]}", None))
    rc, out = run(["herdr", "pane", "list"])
    panes = json.loads(out)["result"]["panes"] if not rc else []
    if rc and tabs:
        report.append((f"tabs skipped: herdr pane list failed: {out[:160]}", None))
        tabs = []
    freed: set[str] = set()  # paths whose tab shell this run closes
    for meta in tabs:
        label, tab_id = str(meta.get("label", "")), meta["tab_id"]
        if not label.startswith(prefix) or PROTECTED.search(label):
            continue
        m = LABEL_LANE.fullmatch(label.removeprefix(prefix))
        rid, aid = (f"R{m[1]}", f"A{m[2]}") if m else (None, None)
        known = _lane(ledger, rid, aid) if rid else None
        mine = [p for p in panes if p.get("tab_id") == tab_id]
        raw = [str(p.get("cwd") or "") for p in mine]
        paths = {c.removesuffix(DELETED) for c in raw}
        statuses = {p.get("agent_status") for p in mine}
        if statuses - SETTLED:
            hold = "active: " + ",".join(sorted(str(x) for x in statuses - SETTLED))
        elif _is_carried([label, *paths], carried):
            hold = "carried"
        elif known is not None and not _finished(known):
            hold = f"lane {rid}/{aid} {known[1] or 'unassigned'}"
        elif known is not None:  # finished, but its worktree is still here and held
            lane_trees = {t for t, ln in tree_lanes.items() if ln == (rid, aid)} | (paths & set(trees))
            hold = "worktree-kept" if any(holds.get(t) for t in lane_trees) else None
        elif not paths or not all(
            _is_lane_path(c.removesuffix(DELETED), root) and (c.endswith(DELETED) or c in trees)
            for c in raw
        ):
            hold = "foreign"  # only a registered lane worktree, or one already deleted
        elif any(p in trees and holds.get(p) for p in paths):
            hold = "worktree-kept"
        else:
            hold = None
        tag = closed(rid) if known is not None else None  # preflight: earlier closed rounds only
        if hold:
            report.append((f"hold tab {tab_id} {label}: {hold}", None))
        elif not go:
            report.append((f"would close tab {tab_id} {label}", tag))
            freed |= paths
        else:
            rc, out = run(["herdr", "tab", "close", tab_id])
            if rc:
                report.append((f"hold tab {tab_id} {label}: close failed: {out[:160]}", None))
            else:
                report.append((f"closed tab {tab_id} {label}", tag))
                freed |= paths

    if go and freed and settle:
        time.sleep(settle)  # let the closed tabs' shells exit
    cwds = busy()  # re-read: closing a tab ends its shell
    if not go:  # a dry run cannot close tabs, so it assumes their shells go
        cwds = [c for c in cwds if not any(c == f or c.startswith(f + "/") for f in freed)]
    removed: set[str] = set()
    for path, hold in holds.items():
        branch = trees[path] or "detached"
        lane = tree_lanes.get(path)
        where = f" {lane[0]}/{lane[1]}" if lane else ""
        tag = closed(lane[0]) if lane else None
        hold = hold or ("busy" if _inside(path, cwds) else None)
        if hold:
            report.append((f"hold {path} ({branch}){where}: {hold}", None))
        elif not go:
            report.append((f"would remove {path} ({branch}){where}", tag))
            removed.add(path)
        else:
            rc, out = run(["git", "-C", path, "status", "--porcelain"])
            links = None if rc else node_modules_links(path, out)
            if links is None:
                report.append((f"hold {path} ({branch}){where}: dirty", None))
                continue
            for link in links:
                link.unlink()  # the symlink only; its target is untouched
            rc, out = run(["git", "worktree", "remove", path], timeout=REMOVE_TIMEOUT)
            if rc and out.startswith(TIMED_OUT):
                report.append((f"hold {path} ({branch}){where}: remove {out}", None))
            elif rc:
                report.append((f"hold {path} ({branch}){where}: remove failed: {out[:160]}", None))
            else:
                report.append((f"removed {path} ({branch}){where}", tag))
                removed.add(path)
    if go and removed:
        run(["git", "worktree", "prune"])
    for path in orphan_dirs(root, trees):  # trees as listed before any removal this run
        report.append((f"orphan {path}: unregistered directory, not removed", None))
    if sweep:
        checked = {b for p, b in trees.items() if b and p not in removed}
        report += prune_branches(
            root=root, go=go, run=run, ledger=ledger, by_branch=by_branch,
            checked=checked, carried=carried,
        )
    if go:
        failed = sorted(
            {subject(line) for line, _ in report if line.startswith("hold ") and FAILED.search(line)}
        )
        try:
            path = state or root / ".agent-runs" / STATE_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(failed, indent=1) + "\n", encoding="utf-8")
        except OSError:
            pass  # best effort: the preflight then counts those items again
    return report


STATE_FILE = "lane-cleanup-failed.json"  # what the last --go run tried and could not do
FAILED = re.compile(r": (close failed|remove failed|remove timed out|delete failed|busy)")


def subject(line: str) -> str:
    """The tab, path or branch a report line is about, e.g. `branch task/a`, `tab t1 live-x`."""
    rest = re.sub(r"^(would close|would remove|would delete|hold|closed|removed|deleted) ", "", line)
    return re.split(r" \(|: ", rest, maxsplit=1)[0]


def _last_failed(root: Path, state: Path | None) -> set[str]:
    try:
        data = json.loads((state or root / ".agent-runs" / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def _refs(run: Run, namespace: str) -> list[tuple[str, str]]:
    rc, out = run(["git", "for-each-ref", "--format=%(refname:short) %(objectname)", namespace])
    if rc:
        raise RuntimeError(f"git for-each-ref failed: {out[:160]}")
    return [tuple(line.split(" ", 1)) for line in out.splitlines() if " " in line]


def prune_branches(
    *,
    root: Path,
    go: bool,
    run: Run,
    ledger: Ledger,
    by_branch: dict[str, tuple[str, str]],
    checked: set[str],
    carried: list[str],
) -> list[tuple[str, str | None]]:
    """Delete branches whose PR is merged or closed (see the module doc); never main or open PRs."""
    rc, out = run(
        ["gh", "pr", "list", "--state", "all", "--limit", "10000",
         "--json", "headRefName,state,headRefOid,baseRefName"]
    )
    if rc:
        return [(f"branches skipped: gh pr list failed: {out[:160]}", None)]
    prs: dict[str, list[dict]] = {}
    for pr in json.loads(out or "[]"):
        prs.setdefault(str(pr.get("headRefName")), []).append(pr)
    open_bases = {str(pr.get("baseRefName")) for f in prs.values() for pr in f if pr.get("state") == "OPEN"}
    protected = {"main", "master", "HEAD", default_branch(root)}
    report: list[tuple[str, str | None]] = []
    remote_deletes: list[tuple[str, str, str, str | None]] = []  # branch, expected tip, why, tag

    def consider(branch: str, tip: str, remote: bool) -> None:
        found = prs.get(branch) or []
        states = {pr.get("state") for pr in found}
        if branch in protected or not found or "OPEN" in states:
            return  # never main; PR-less and open-PR branches are not ours to prune
        name = f"remote branch origin/{branch}" if remote else f"branch {branch}"
        lane = by_branch.get(branch)
        known = _lane(ledger, *lane) if lane else None
        if branch in open_bases:
            hold = "base-of-open-pr"
        elif not remote and branch in checked:
            hold = "checked-out"
        elif known is not None and not _finished(known):
            hold = f"lane {lane[0]}/{lane[1]} {known[1] or 'unassigned'}"
        elif _is_carried([branch], carried):
            hold = "carried"
        elif not any(
            pr.get("headRefOid") == tip
            or run(["git", "merge-base", "--is-ancestor", tip, str(pr.get("headRefOid"))])[0] == 0
            for pr in found
        ):
            hold = "newer-than-pr"
        else:
            hold = None
        why = "merged" if "MERGED" in states else "closed"
        tag = lane[0] if lane and (ledger.get(lane[0]) or {}).get("state") == "closed" else None
        if hold:
            report.append((f"hold {name}: {hold}", None))
            return
        if not go:
            report.append((f"would delete {name}: {why}", tag))
            return
        if remote:
            remote_deletes.append((branch, tip, why, tag))
            return
        rc, out = run(["git", "branch", "-D", branch])
        if rc:
            report.append((f"hold {name}: delete failed: {out[:160]}", None))
        else:
            report.append((f"deleted {name}: {why}", tag))

    for branch, tip in _refs(run, "refs/heads"):
        consider(branch, tip, remote=False)
    rc, out = run(["git", "fetch", "--prune", "origin"])  # drop stale tracking refs first
    if rc:
        report.append((f"branches skipped: remote: git fetch --prune failed: {out[:160]}", None))
        return report
    for ref, tip in _refs(run, "refs/remotes/origin"):
        if ref.startswith("origin/") and ref != "origin":
            consider(ref.removeprefix("origin/"), tip, remote=True)
    for i in range(0, len(remote_deletes), PUSH_BATCH):
        report += _push_deletes(run, remote_deletes[i : i + PUSH_BATCH])
    return report


PUSH_BATCH = 50


def _push_deletes(run: Run, batch: list[tuple[str, str, str, str | None]]) -> list:
    """One push deleting many origin branches, each leased to the tip this run inspected."""
    leases = [f"--force-with-lease=refs/heads/{b}:{tip}" for b, tip, _, _ in batch]
    specs = [f":refs/heads/{b}" for b, _, _, _ in batch]
    rc, out = run(["git", "push", "--porcelain", *leases, "origin", *specs], timeout=REMOVE_TIMEOUT)
    report = []
    for branch, _, why, tag in batch:
        name = f"remote branch origin/{branch}"
        spec = f":refs/heads/{branch}"
        if f"unable to delete '{branch}': remote ref does not exist" in out:
            run(["git", "update-ref", "-d", f"refs/remotes/origin/{branch}"])
            report.append((f"deleted {name}: {why} (already gone)", tag))
        elif any(line.startswith("-\t" + spec + "\t") for line in out.splitlines()):
            report.append((f"deleted {name}: {why}", tag))
        else:
            mine = [line for line in out.splitlines() if spec + "\t" in line] or [out[:160]]
            report.append((f"hold {name}: delete failed: {mine[0][:160]}", None))
    return report


def default_branch(root: Path = ROOT) -> str:
    try:
        with (root / ".agent" / "config.toml").open("rb") as fh:
            return str(tomllib.load(fh).get("project", {}).get("default_branch", "main"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, AttributeError):
        return "main"


def cleanup(
    *,
    root: Path = ROOT,
    prefix: str | None = None,
    go: bool = False,
    handoff: str | None = None,
    run: Run = _run,
    busy: Callable[[], list[str]] = _busy,
    settle: float = 2.0,
    ledger: Ledger | None = None,
    sweep: bool = False,
    state: Path | None = None,
) -> list[str]:
    """Tabs first, so a finished lane's idle shell no longer pins its worktree; then worktrees."""
    items = _items(
        root=root, prefix=prefix, go=go, handoff=handoff, run=run, busy=busy, settle=settle,
        ledger=ledger, sweep=sweep, state=state,
    )
    return [line for line, _ in items]


def preflight(
    *,
    root: Path = ROOT,
    prefix: str | None = None,
    handoff: str | None = None,
    run: Run = _run,
    busy: Callable[[], list[str]] = _busy,
    ledger: Ledger | None = None,
    state: Path | None = None,
) -> list[str]:
    """What a closed round still has that `--go --sweep` would remove, or why that is unknown.

    A dry run already holds trees busy with other processes; items the last --go run tried and
    failed on (recorded in .agent-runs/lane-cleanup-failed.json) are not counted either.
    """
    items = _items(
        root=root, prefix=prefix, go=False, handoff=handoff, run=run, busy=busy, settle=0,
        ledger=ledger, sweep=True,
    )
    failed = _last_failed(root, state)
    problems = [
        f"{rid}: {line}"
        for line, rid in items
        if rid and line.startswith("would ") and subject(line) not in failed
    ]
    problems += [line for line, _ in items if "skipped:" in line or line.endswith(": unreachable")]
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--go", action="store_true", help="act; without it, a dry run")
    parser.add_argument(
        "--all-rounds", action="store_true", help="every ledger round (the default; for parity)"
    )
    parser.add_argument(
        "--sweep", action="store_true", help="also .claude/worktrees and merged/closed branches"
    )
    parser.add_argument(
        "--preflight", action="store_true", help="exit 1 while a closed round has leftovers"
    )
    args = parser.parse_args(argv)
    if args.preflight:
        problems = preflight()
        for line in problems:
            print(f"leftover {line}")
        if problems:
            print("refusing: run `python3 scripts/lane_cleanup.py --go --sweep` first")
        return 1 if problems else 0
    lines = cleanup(go=args.go, sweep=args.sweep)
    for line in lines + summary(lines):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

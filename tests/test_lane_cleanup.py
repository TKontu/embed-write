"""Lane cleanup: drop finished lanes' worktrees and close their Herdr tabs, by rule only."""

import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lane_cleanup.py"
spec = importlib.util.spec_from_file_location("lane_cleanup", SCRIPT)
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

ROOT = Path("/work/repo")
LANES = "/work/repo-lanes"


class Fake:
    """git, gh and herdr doubles plus a process table; records every mutating call."""

    def __init__(self, trees, prs, tabs=(), panes=(), dirty=(), unpushed=(), busy=()):
        self.trees, self.prs = trees, prs  # {path: branch}, {branch: [states newest first]}
        self.tabs, self.panes = list(tabs), list(panes)
        self.dirty, self.unpushed, self.busy_paths = set(dirty), set(unpushed), list(busy)
        self.done = []

    def run(self, cmd):
        cmd = list(cmd)
        if cmd[:4] == ["git", "worktree", "list", "--porcelain"]:
            blocks = [f"worktree {ROOT}\nHEAD {'0' * 40}\nbranch refs/heads/main"]
            blocks += [
                f"worktree {p}\nHEAD {'1' * 40}\nbranch refs/heads/{b}" for p, b in self.trees.items()
            ]
            return 0, "\n\n".join(blocks)
        if cmd[:2] == ["git", "-C"] and cmd[3:5] == ["status", "--porcelain"]:
            return 0, " M x.py" if cmd[2] in self.dirty else ""
        if cmd[:2] == ["git", "-C"] and cmd[3] == "rev-list":
            return 0, "abc" if cmd[2] in self.unpushed else ""
        if cmd[:3] == ["gh", "pr", "list"]:
            branch = cmd[cmd.index("--head") + 1]
            return 0, json.dumps([{"state": s} for s in self.prs.get(branch, [])])
        if cmd[:3] == ["herdr", "tab", "list"]:
            return 0, json.dumps({"result": {"tabs": self.tabs}})
        if cmd[:3] == ["herdr", "pane", "list"]:
            return 0, json.dumps({"result": {"panes": self.panes}})
        if cmd[:3] in (["git", "worktree", "remove"], ["herdr", "tab", "close"]):
            self.done.append(cmd)
            return 0, ""
        if cmd[:3] == ["git", "worktree", "prune"]:
            return 0, ""
        return 1, f"unexpected {cmd}"

    def busy(self):
        return self.busy_paths


def tab(tid, label, cwd, status="idle"):
    return (
        {"tab_id": tid, "label": label, "workspace_id": "w"},
        {"tab_id": tid, "pane_id": tid + "p", "cwd": cwd, "agent_status": status},
    )


def clean(fake, go=True, handoff=""):
    return lc.cleanup(
        root=ROOT, prefix="live-repo-", go=go, handoff=handoff, run=fake.run, busy=fake.busy,
        settle=0,
    )


class WorktreeTests(unittest.TestCase):
    def test_removes_a_merged_lane_worktree_but_never_the_main_checkout(self):
        fake = Fake({f"{LANES}/r1-a1": "task/a"}, {"task/a": ["MERGED"]})
        clean(fake)
        self.assertEqual(fake.done, [["git", "worktree", "remove", f"{LANES}/r1-a1"]])

    def test_closed_pr_counts_as_finished_but_any_open_pr_keeps_the_tree(self):
        fake = Fake(
            {f"{LANES}/a": "task/a", f"{LANES}/b": "task/b"},
            {"task/a": ["CLOSED"], "task/b": ["MERGED", "OPEN"]},
        )
        clean(fake)
        self.assertEqual(fake.done, [["git", "worktree", "remove", f"{LANES}/a"]])

    def test_holds_dirty_unpushed_busy_and_pr_less_trees(self):
        trees = {f"{LANES}/{n}": f"task/{n}" for n in ("dirty", "unpushed", "busy", "nopr")}
        prs = {f"task/{n}": ["MERGED"] for n in ("dirty", "unpushed", "busy")}
        fake = Fake(
            trees,
            prs,
            dirty=[f"{LANES}/dirty"],
            unpushed=[f"{LANES}/unpushed"],
            busy=[f"{LANES}/busy/sub"],
        )
        report = clean(fake)
        self.assertEqual(fake.done, [])
        for reason in ("dirty", "unpushed", "busy", "no-pr"):
            self.assertTrue(any(reason in line for line in report), (reason, report))

    def test_holds_a_tree_named_as_carried_in_the_handoff(self):
        fake = Fake({f"{LANES}/r9-a1": "task/a"}, {"task/a": ["MERGED"]})
        handoff = f"## Carried lanes\n- live-repo-r9-a1 at {LANES}/r9-a1 carries over; do not halt\n"
        report = clean(fake, handoff=handoff)
        self.assertEqual(fake.done, [])
        self.assertTrue(any("carried" in line for line in report))

    def test_a_dry_run_changes_nothing(self):
        fake = Fake({f"{LANES}/r1-a1": "task/a"}, {"task/a": ["MERGED"]})
        report = clean(fake, go=False)
        self.assertEqual(fake.done, [])
        self.assertTrue(any(line.startswith("would remove") for line in report))


class TabTests(unittest.TestCase):
    def test_closes_an_idle_lane_tab_once_its_worktree_is_gone(self):
        meta, pane = tab("t1", "live-repo-r1-a1", f"{LANES}/r1-a1 (deleted)")
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        clean(fake)
        self.assertEqual(fake.done, [["herdr", "tab", "close", "t1"]])

    def test_closes_the_tab_of_a_tree_removed_in_the_same_run(self):
        meta, pane = tab("t1", "live-repo-r1-a1", f"{LANES}/r1-a1")
        fake = Fake({f"{LANES}/r1-a1": "task/a"}, {"task/a": ["MERGED"]}, tabs=[meta], panes=[pane])
        clean(fake)
        self.assertIn(["herdr", "tab", "close", "t1"], fake.done)

    def test_a_tree_busy_only_with_its_own_idle_tab_shell_goes_after_the_tab(self):
        meta, pane = tab("t1", "live-repo-r1-a1", f"{LANES}/r1-a1")
        fake = Fake(
            {f"{LANES}/r1-a1": "task/a"},
            {"task/a": ["MERGED"]},
            tabs=[meta],
            panes=[pane],
            busy=[f"{LANES}/r1-a1"],
        )
        real_run = fake.run

        def run(cmd):  # closing the tab ends its shell
            if list(cmd)[:3] == ["herdr", "tab", "close"]:
                fake.busy_paths = []
            return real_run(cmd)

        fake.run = run
        clean(fake)
        self.assertEqual(
            fake.done,
            [["herdr", "tab", "close", "t1"], ["git", "worktree", "remove", f"{LANES}/r1-a1"]],
        )

    def test_a_tree_still_busy_after_its_tab_closed_is_held(self):
        meta, pane = tab("t1", "live-repo-r1-a1", f"{LANES}/r1-a1")
        fake = Fake(
            {f"{LANES}/r1-a1": "task/a"},
            {"task/a": ["MERGED"]},
            tabs=[meta],
            panes=[pane],
            busy=[f"{LANES}/r1-a1"],
        )
        report = clean(fake)
        self.assertEqual(fake.done, [["herdr", "tab", "close", "t1"]])
        self.assertTrue(any("busy" in line for line in report))

    def test_keeps_tabs_that_are_working_carried_held_foreign_or_protected(self):
        tabs = [
            tab("w", "live-repo-r1-a1", f"{LANES}/gone-w (deleted)", status="working"),
            tab("c", "live-repo-r9-a1", f"{LANES}/gone-c (deleted)"),
            tab("h", "live-repo-r2-a1", f"{LANES}/open"),
            tab("o", "live-other-r1-a1", f"{LANES}/gone-o (deleted)"),
            tab("p", "live-repo-planner", f"{LANES}/gone-p (deleted)"),
            tab("m", "live-repo-r3-a1", str(ROOT)),
        ]
        fake = Fake(
            {f"{LANES}/open": "task/open"},
            {"task/open": ["OPEN"]},
            tabs=[t for t, _ in tabs],
            panes=[p for _, p in tabs],
        )
        clean(fake, handoff="## Carried\n- live-repo-r9-a1 carries over\n")
        self.assertEqual(fake.done, [])

    def test_keeps_a_tab_in_a_sibling_dir_that_is_not_a_worktree(self):
        meta, pane = tab("t1", "live-repo-r1-a1", "/work/repo-results")
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        clean(fake)
        self.assertEqual(fake.done, [])

    def test_keeps_a_tab_whose_pane_is_blocked_or_in_any_unknown_state(self):
        for status in ("blocked", "waiting", "busy"):
            meta, pane = tab("t1", "live-repo-r1-a1", f"{LANES}/r1-a1 (deleted)", status=status)
            fake = Fake({}, {}, tabs=[meta], panes=[pane])
            clean(fake)
            self.assertEqual(fake.done, [], status)

    def test_no_carried_lanes_line_does_not_carry_anything(self):
        meta, pane = tab("t1", "live-repo-r49-a1", f"{LANES}/r49-a1 (deleted)")
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        clean(fake, handoff="- No carried lanes. Tabs live-repo-r49-a1 are finished and may be closed.\n")
        self.assertEqual(fake.done, [["herdr", "tab", "close", "t1"]])


if __name__ == "__main__":
    unittest.main()

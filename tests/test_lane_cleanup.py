"""Lane cleanup: drop finished lanes' worktrees and close their Herdr tabs, by rule only."""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
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
        self.done, self.timeouts, self.remove_out = [], {}, None

    def run(self, cmd, timeout=None):
        cmd = list(cmd)
        self.timeouts[tuple(cmd[:3])] = timeout
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
            if self.remove_out and cmd[:3] == ["git", "worktree", "remove"]:
                return self.remove_out
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


class LanePrefixTests(unittest.TestCase):
    def _root(self, toml):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "My Repo"
        (root / ".agent").mkdir(parents=True)
        (root / ".agent" / "config.toml").write_text(toml)
        return root

    def test_non_table_supervisor_falls_back_to_root_name(self):
        self.assertEqual(lc.lane_prefix(self._root('supervisor = "x"\n')), "live-my-repo-")

    def test_invalid_toml_falls_back_to_root_name(self):
        self.assertEqual(lc.lane_prefix(self._root("[supervisor\n")), "live-my-repo-")

    def test_invalid_utf8_falls_back_to_root_name(self):
        root = self._root("")
        (root / ".agent" / "config.toml").write_bytes(b"\xff\xfe")
        self.assertEqual(lc.lane_prefix(root), "live-my-repo-")

    def test_supervisor_name_still_wins(self):
        root = self._root('[supervisor]\nname = "Alpha"\n')
        self.assertEqual(lc.lane_prefix(root), "live-alpha-")


class WorktreeTests(unittest.TestCase):
    def test_removes_a_merged_lane_worktree_but_never_the_main_checkout(self):
        fake = Fake({f"{LANES}/r1-a1": "task/a"}, {"task/a": ["MERGED"]})
        clean(fake)
        self.assertEqual(fake.done, [["git", "worktree", "remove", f"{LANES}/r1-a1"]])

    def test_remove_gets_the_long_timeout(self):
        fake = Fake({f"{LANES}/r1-a1": "task/a"}, {"task/a": ["MERGED"]})
        clean(fake)
        self.assertEqual(fake.timeouts[("git", "worktree", "remove")], 600)

    def test_a_remove_timeout_is_reported_plainly(self):
        fake = Fake({f"{LANES}/r1-a1": "task/a"}, {"task/a": ["MERGED"]})
        fake.remove_out = lc._run(["sleep", "5"], timeout=0.01)
        report = clean(fake)
        self.assertIn(f"hold {LANES}/r1-a1 (task/a): remove timed out after 0.01s", report)
        self.assertNotIn(f"removed {LANES}/r1-a1 (task/a)", report)

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

        def run(cmd, timeout=None):  # closing the tab ends its shell
            if list(cmd)[:3] == ["herdr", "tab", "close"]:
                fake.busy_paths = []
            return real_run(cmd, timeout=timeout)

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


class NodeModulesLinkTests(unittest.TestCase):
    """Real temp repo and worktree: only untracked node_modules symlinks are tolerated."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.lane = str(self.tmp / "repo-lanes" / "r1-a1")
        self.target = self.tmp / "shared-node_modules"
        (self.target / "pkg").mkdir(parents=True)
        (self.target / "pkg" / "index.js").write_text("x\n")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]
        subprocess.run([*git, "init", "-q", str(self.root)], check=True)
        (self.root / "editor").mkdir()
        (self.root / "editor" / "a.txt").write_text("a\n")
        subprocess.run([*git, "-C", str(self.root), "add", "."], check=True)
        subprocess.run([*git, "-C", str(self.root), "commit", "-qm", "i"], check=True)
        subprocess.run(
            [*git, "-C", str(self.root), "worktree", "add", "-q", "-b", "task/a", self.lane],
            check=True,
        )

    def run_git(self, cmd, timeout=None):
        cmd = list(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return 0, json.dumps([{"state": "MERGED"}])
        if cmd[:1] == ["herdr"]:
            return 1, "no herdr"
        if cmd[:2] == ["git", "-C"] and cmd[3] == "rev-list":
            return 0, ""  # no remote in the temp repo; pretend pushed
        done = subprocess.run(cmd, capture_output=True, text=True, cwd=self.root)
        return done.returncode, done.stdout.strip() or done.stderr.strip()

    def clean(self, go):
        return lc.cleanup(
            root=self.root, prefix="live-repo-", go=go, handoff="", run=self.run_git,
            busy=lambda: [], settle=0,
        )

    def link(self, rel):
        os.symlink(self.target, Path(self.lane) / rel)

    def test_symlink_only_untracked_is_not_held_and_go_unlinks_the_link_only(self):
        self.link("node_modules")
        self.link("editor/node_modules")
        report = self.clean(go=True)
        self.assertIn(f"removed {self.lane} (task/a)", report, report)
        self.assertFalse(os.path.lexists(self.lane))
        self.assertEqual((self.target / "pkg" / "index.js").read_text(), "x\n")

    def test_dry_run_unlinks_nothing(self):
        self.link("editor/node_modules")
        report = self.clean(go=False)
        self.assertIn(f"would remove {self.lane} (task/a)", report, report)
        self.assertTrue(os.path.islink(Path(self.lane) / "editor" / "node_modules"))

    def test_a_real_node_modules_dir_is_dirty(self):
        self.link("node_modules")
        (Path(self.lane) / "editor" / "node_modules").mkdir()
        (Path(self.lane) / "editor" / "node_modules" / "f.js").write_text("y\n")
        report = self.clean(go=True)
        self.assertTrue(any(line.endswith(": dirty") for line in report), report)
        self.assertTrue(os.path.islink(Path(self.lane) / "node_modules"))

    def test_any_other_untracked_file_or_tracked_change_is_dirty(self):
        for extra in ("stray.txt", "editor/a.txt"):
            with self.subTest(extra=extra):
                self.link("node_modules")
                (Path(self.lane) / extra).write_text("z\n")
                report = self.clean(go=True)
                self.assertTrue(any(line.endswith(": dirty") for line in report), report)
                self.assertTrue(os.path.islink(Path(self.lane) / "node_modules"))
                subprocess.run(["git", "-C", self.lane, "checkout", "-q", "--", "."], check=True)
                subprocess.run(["git", "-C", self.lane, "clean", "-qf", "--", "stray.txt"])
                os.unlink(Path(self.lane) / "node_modules")


INREPO = f"{ROOT}/worktrees"


class InRepoWorktreeTests(unittest.TestCase):
    """A lane at <root>/worktrees/<name> follows the sibling-path rules; nothing else inside does."""

    def test_dry_run_would_remove_and_go_removes_a_merged_clean_tree(self):
        fake = Fake({f"{INREPO}/x": "task/x"}, {"task/x": ["MERGED"]})
        report = clean(fake, go=False)
        self.assertEqual(fake.done, [])
        self.assertIn(f"would remove {INREPO}/x (task/x)", report)
        clean(fake)
        self.assertEqual(fake.done, [["git", "worktree", "remove", f"{INREPO}/x"]])

    def test_its_idle_tab_is_closed_not_foreign(self):
        meta, pane = tab("t1", "live-repo-r1-a1", f"{INREPO}/x")
        fake = Fake({f"{INREPO}/x": "task/x"}, {"task/x": ["MERGED"]}, tabs=[meta], panes=[pane])
        report = clean(fake)
        self.assertIn(["herdr", "tab", "close", "t1"], fake.done)
        self.assertFalse(any("foreign" in line for line in report), report)

    def test_its_deleted_tree_tab_is_closed(self):
        meta, pane = tab("t1", "live-repo-r1-a1", f"{INREPO}/x (deleted)")
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        clean(fake)
        self.assertEqual(fake.done, [["herdr", "tab", "close", "t1"]])

    def test_dirty_pr_less_and_carried_trees_are_held(self):
        trees = {f"{INREPO}/{n}": f"task/{n}" for n in ("dirty", "nopr", "r9-a1")}
        prs = {"task/dirty": ["MERGED"], "task/r9-a1": ["MERGED"]}
        fake = Fake(trees, prs, dirty=[f"{INREPO}/dirty"])
        handoff = f"## Carried lanes\n- live-repo-r9-a1 at {INREPO}/r9-a1 carries over\n"
        report = clean(fake, handoff=handoff)
        self.assertEqual(fake.done, [])
        for reason in ("dirty", "no-pr", "carried"):
            self.assertTrue(any(reason in line for line in report), (reason, report))

    def test_other_paths_inside_the_main_checkout_are_not_lanes(self):
        others = [f"{ROOT}/.claude/worktrees/agent-x", INREPO, f"{INREPO}/a/b", f"{ROOT}/other/x"]
        for path in others:
            self.assertFalse(lc._is_lane_path(path, ROOT), path)
        self.assertFalse(lc._is_lane_path(str(ROOT), ROOT))
        self.assertTrue(lc._is_lane_path(f"{INREPO}/x", ROOT))
        tabs = [tab(f"t{i}", f"live-repo-r{i}-a1", p) for i, p in enumerate(others)]
        fake = Fake(
            {p: f"task/{i}" for i, p in enumerate(others)},
            {f"task/{i}": ["MERGED"] for i in range(len(others))},
            tabs=[t for t, _ in tabs],
            panes=[p for _, p in tabs],
        )
        report = clean(fake)
        self.assertEqual(fake.done, [])
        for i, path in enumerate(others):
            self.assertTrue(any(f"tab t{i} " in l and "foreign" in l for l in report), report)
            self.assertFalse(any(f"{path} (" in l for l in report), report)

    def test_sibling_paths_are_still_lanes(self):
        self.assertTrue(lc._is_lane_path(f"{LANES}/r1-a1", ROOT))
        self.assertTrue(lc._is_lane_path("/work/repo-r9-a1", ROOT))
        self.assertFalse(lc._is_lane_path("/work/repository", ROOT))


if __name__ == "__main__":
    unittest.main()

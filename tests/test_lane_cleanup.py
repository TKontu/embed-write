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


class OrphanDirTests(unittest.TestCase):
    """Directories at lane paths that git does not know are reported, never touched (R220/R216)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        (self.root / "worktrees").mkdir(parents=True)

    def _clean(self, trees, go):
        fake = Fake({str(p): b for p, b in trees.items()}, {})
        original = ROOT
        globals()["ROOT"] = self.root  # Fake lists the main checkout at ROOT
        self.addCleanup(globals().__setitem__, "ROOT", original)
        report = lc.cleanup(
            root=self.root, prefix="live-repo-", go=go, handoff="", run=fake.run,
            busy=fake.busy, settle=0,
        )
        return report, fake

    def _orphans(self, report):
        return [line for line in report if line.startswith("orphan ")]

    def test_unregistered_sibling_is_reported_in_dry_run_and_go_and_kept(self):
        orphan = Path(f"{self.root}-r9-a1")
        orphan.mkdir()
        (orphan / "f.txt").write_text("x")
        for go in (False, True):
            report, fake = self._clean({}, go)
            self.assertEqual(
                self._orphans(report), [f"orphan {orphan}: unregistered directory, not removed"]
            )
            self.assertEqual(fake.done, [])
            self.assertTrue((orphan / "f.txt").is_file())

    def test_registered_worktree_and_its_container_are_not_orphans(self):
        tree = Path(f"{self.root}-lanes") / "r9-a1"
        tree.mkdir(parents=True)
        sib = Path(f"{self.root}-r9-a2")
        sib.mkdir()
        for go in (False, True):
            report, _ = self._clean({tree: "t1", sib: "t2"}, go)
            self.assertEqual(self._orphans(report), [])

    def test_container_without_worktrees_is_not_reported(self):
        for name in ("results", "lanes", "worktrees"):
            Path(f"{self.root}-{name}").mkdir()
        report, _ = self._clean({}, False)
        self.assertEqual(self._orphans(report), [])

    def test_plain_file_at_a_sibling_path_is_not_reported(self):
        Path(f"{self.root}-x.log").write_text("log")
        report, _ = self._clean({}, False)
        self.assertEqual(self._orphans(report), [])

    def test_unregistered_in_repo_worktrees_dir_is_reported(self):
        orphan = self.root / "worktrees" / "r9-a1"
        orphan.mkdir()
        registered = self.root / "worktrees" / "r9-a2"
        registered.mkdir()
        for go in (False, True):
            report, _ = self._clean({registered: "t2"}, go)
            self.assertEqual(
                self._orphans(report), [f"orphan {orphan}: unregistered directory, not removed"]
            )
            self.assertTrue(orphan.is_dir())

    def test_unrelated_siblings_are_not_reported(self):
        Path(f"{self.root}x").mkdir()
        (self.root.parent / "other").mkdir()
        report, _ = self._clean({}, False)
        self.assertEqual(self._orphans(report), [])


if __name__ == "__main__":
    unittest.main()


def ledger(**rounds):
    """ledger(R5=("closed", {"A1": ("task/a", "merged")})) -> {round id: manifest}."""
    return {
        rid: {
            "id": rid,
            "state": state,
            "assignments": {a: {"branch": b, "state": s} for a, (b, s) in lanes.items()},
        }
        for rid, (state, lanes) in rounds.items()
    }


class BranchFake(Fake):
    """Adds the bulk PR listing, ref listings, ancestry and branch deletion."""

    def __init__(self, *args, local=(), remote=(), pr_heads=None, ahead=(), **kw):
        super().__init__(*args, **kw)
        self.local, self.remote = list(local), list(remote)  # branch names; tip "t-<name>"
        self.pr_heads = pr_heads or {}  # {branch: [(state, head oid)]}, default head = tip
        self.ahead = set(ahead)  # branches whose tip is newer than every PR head
        self.stale, self.leased, self.bases, self.order = set(), set(), {}, []  # bases: {head: base of OPEN PR}

    def run(self, cmd, timeout=None):
        cmd = list(cmd)
        if cmd[:3] == ["gh", "pr", "list"] and "--head" not in cmd:
            rows = []
            for branch, states in self.prs.items():
                head = f"h-{branch}" if branch in self.ahead else f"t-{branch}"
                heads = self.pr_heads.get(branch) or [(s, head) for s in states]
                rows += [
                    {"headRefName": branch, "state": s, "headRefOid": h,
                     "baseRefName": self.bases.get(branch, "main")}
                    for s, h in heads
                ]
            return 0, json.dumps(rows)
        if cmd[:2] == ["git", "for-each-ref"]:
            self.order.append(cmd[-1])
            if cmd[-1] == "refs/heads":
                return 0, "\n".join(f"{b} t-{b}" for b in ["main", *self.local])
            return 0, "\n".join(f"origin/{b} t-{b}" for b in ["HEAD", "main", *self.remote])
        if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
            branch = cmd[3].removeprefix("t-")
            return (1, "") if branch in self.ahead else (0, "")
        if cmd[:3] == ["git", "branch", "-D"] or cmd[:3] == ["git", "update-ref", "-d"]:
            self.done.append(cmd)
            return 0, ""
        if cmd[:3] == ["git", "fetch", "--prune"]:
            self.order.append("fetch")
            return 0, ""
        if cmd[:2] == ["git", "push"]:
            self.done.append(cmd)
            out, rc = [], 0
            for spec in (c for c in cmd if c.startswith(":refs/heads/")):
                b = spec.removeprefix(":refs/heads/")
                if b in self.stale:
                    out.append(f"error: unable to delete '{b}': remote ref does not exist")
                    rc = 1
                elif b in self.leased:
                    out.append(f"!\t{spec}\t[rejected] (stale info)")
                    rc = 1
                else:
                    out.append(f"-\t{spec}\t[deleted]")
            return rc, "\n".join(out)
        return super().run(cmd, timeout=timeout)


def sweep(fake, go=True, handoff="", led=None, **kw):
    return lc.cleanup(
        root=ROOT, prefix="live-repo-", go=go, handoff=handoff, run=fake.run, busy=fake.busy,
        settle=0, ledger=led or {}, **kw,
    )


class LedgerTabTests(unittest.TestCase):
    """A lane tab maps to R<N>/A<M> by its label, whatever the pane's cwd."""

    def test_closes_a_tab_in_the_main_checkout_once_its_lane_merged(self):
        meta, pane = tab("t1", "live-repo-r5-a1", str(ROOT))
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        led = ledger(R5=("open", {"A1": ("task/a", "merged")}))
        sweep(fake, led=led)
        self.assertEqual(fake.done, [["herdr", "tab", "close", "t1"]])

    def test_closes_a_cancelled_lane_tab_and_any_tab_of_a_closed_round(self):
        a, pa = tab("t1", "live-repo-r5-a1", str(ROOT))
        b, pb = tab("t2", "live-repo-r6-a2", f"{ROOT}/.claude/worktrees/x")
        fake = Fake({}, {}, tabs=[a, b], panes=[pa, pb])
        led = ledger(
            R5=("open", {"A1": ("task/a", "cancelled")}),
            R6=("closed", {"A1": ("task/b", "merged")}),
        )
        sweep(fake, led=led)
        self.assertEqual(
            fake.done, [["herdr", "tab", "close", "t1"], ["herdr", "tab", "close", "t2"]]
        )

    def test_holds_an_unresolved_lane_of_an_open_round(self):
        meta, pane = tab("t1", "live-repo-r7-a1", str(ROOT))
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        report = sweep(fake, led=ledger(R7=("open", {"A1": ("task/a", "result-ready")})))
        self.assertEqual(fake.done, [])
        self.assertIn("hold tab t1 live-repo-r7-a1: lane R7/A1 result-ready", report)

    def test_keeps_every_existing_safety_hold(self):
        led = ledger(R5=("closed", {"A1": ("task/a", "merged"), "A2": ("task/b", "merged")}))
        working, pw = tab("t1", "live-repo-r5-a1", str(ROOT), status="working")
        blocked, pb = tab("t2", "live-repo-r5-a2", str(ROOT), status="blocked")
        carried, pc = tab("t3", "live-repo-r5-a3", str(ROOT))
        prot, pp = tab("t4", "live-repo-r5-a1-planner", str(ROOT))
        other, po = tab("t5", "live-other-r5-a1", str(ROOT))
        fake = Fake(
            {}, {}, tabs=[working, blocked, carried, prot, other], panes=[pw, pb, pc, pp, po]
        )
        handoff = "## Carried lanes\n- live-repo-r5-a3 carries over\n"
        report = sweep(fake, led=led, handoff=handoff)
        self.assertEqual(fake.done, [])
        self.assertIn("hold tab t1 live-repo-r5-a1: active: working", report)
        self.assertIn("hold tab t2 live-repo-r5-a2: active: blocked", report)
        self.assertIn("hold tab t3 live-repo-r5-a3: carried", report)

    def test_a_label_outside_the_ledger_falls_back_to_the_cwd_rule(self):
        meta, pane = tab("t1", "live-repo-r9-a1", str(ROOT))
        fake = Fake({}, {}, tabs=[meta], panes=[pane])
        report = sweep(fake, led=ledger(R5=("closed", {})))
        self.assertIn("hold tab t1 live-repo-r9-a1: foreign", report)


class ClosedRoundWorktreeTests(unittest.TestCase):
    LED = ledger(R5=("closed", {"A1": ("task/a", "merged")}), R7=("open", {"A1": ("task/c", "assigned")}))

    def test_removes_a_clean_pushed_pr_less_tree_of_a_closed_round(self):
        fake = Fake({f"{LANES}/r5-a1": "task/a"}, {})
        sweep(fake, led=self.LED)
        self.assertEqual(fake.done, [["git", "worktree", "remove", f"{LANES}/r5-a1"]])

    def test_maps_a_tree_by_its_branch_when_the_path_has_no_lane_name(self):
        fake = Fake({f"{ROOT}-wt-x": "task/a"}, {})
        sweep(fake, led=self.LED)
        self.assertEqual(fake.done, [["git", "worktree", "remove", f"{ROOT}-wt-x"]])

    def test_keeps_dirty_or_unpushed_trees_and_names_round_and_lane(self):
        led = ledger(R5=("closed", {"A1": ("task/a", "merged"), "A2": ("task/b", "merged")}))
        fake = Fake(
            {f"{LANES}/r5-a1": "task/a", f"{LANES}/r5-a2": "task/b"},
            {"task/a": ["MERGED"]},
            dirty=[f"{LANES}/r5-a1"],
            unpushed=[f"{LANES}/r5-a2"],
        )
        report = sweep(fake, led=led)
        self.assertEqual(fake.done, [])
        self.assertIn(f"hold {LANES}/r5-a1 (task/a) R5/A1: dirty", report)
        self.assertIn(f"hold {LANES}/r5-a2 (task/b) R5/A2: unpushed", report)

    def test_an_open_pr_still_keeps_a_closed_rounds_tree(self):
        fake = Fake({f"{LANES}/r5-a1": "task/a"}, {"task/a": ["OPEN"]})
        report = sweep(fake, led=self.LED)
        self.assertEqual(fake.done, [])
        self.assertIn(f"hold {LANES}/r5-a1 (task/a) R5/A1: open-pr", report)

    def test_an_open_rounds_pr_less_tree_is_still_held(self):
        fake = Fake({f"{LANES}/r7-a1": "task/c"}, {})
        report = sweep(fake, led=self.LED)
        self.assertEqual(fake.done, [])
        self.assertIn(f"hold {LANES}/r7-a1 (task/c) R7/A1: no-pr", report)

    def test_sweep_adds_claude_agent_worktrees_but_never_forces(self):
        path = f"{ROOT}/.claude/worktrees/agent-1"
        fake = BranchFake({path: "task/z"}, {"task/z": ["MERGED"]})
        sweep(fake, led=self.LED)
        self.assertEqual(fake.done, [])
        sweep(fake, led=self.LED, sweep=True)
        self.assertEqual(fake.done, [["git", "worktree", "remove", path]])
        self.assertFalse(any("--force" in c for c in fake.done))


class BranchPruneTests(unittest.TestCase):
    def test_deletes_finished_local_branches_and_remote_ones_only_under_go(self):
        fake = BranchFake(
            {f"{LANES}/r5-a1": "task/kept"},
            {"task/m": ["MERGED"], "task/c": ["CLOSED"], "task/kept": ["OPEN"]},
            local=["task/m", "task/c", "task/kept"],
            remote=["task/m"],
        )
        report = sweep(fake, go=False, sweep=True)
        self.assertEqual(fake.done, [])
        self.assertIn("would delete branch task/m: merged", report)
        self.assertIn("would delete remote branch origin/task/m: merged", report)
        sweep(fake, sweep=True)
        self.assertIn(["git", "branch", "-D", "task/m"], fake.done)
        self.assertIn(["git", "branch", "-D", "task/c"], fake.done)
        [push] = [c for c in fake.done if c[:2] == ["git", "push"]]
        self.assertIn("--force-with-lease=refs/heads/task/m:t-task/m", push)
        self.assertIn(":refs/heads/task/m", push)
        self.assertNotIn(":refs/heads/task/c", push)  # not on origin

    def test_never_touches_main_open_pr_checked_out_pr_less_or_newer_branches(self):
        fake = BranchFake(
            {f"{LANES}/r5-a1": "task/out"},
            {"main": ["MERGED"], "task/o": ["MERGED", "OPEN"], "task/out": ["MERGED"],
             "task/new": ["MERGED"]},
            local=["task/o", "task/out", "task/none", "task/new"],
            remote=["task/o", "task/none", "task/new"],
            dirty=[f"{LANES}/r5-a1"],
            ahead=["task/new"],
        )
        report = sweep(fake, sweep=True)
        self.assertEqual(fake.done, [])
        self.assertIn("hold branch task/new: newer-than-pr", report)
        self.assertIn("hold branch task/out: checked-out", report)

    def test_branches_of_an_open_rounds_unresolved_lane_are_kept(self):
        fake = BranchFake({}, {"task/c": ["CLOSED"]}, local=["task/c"])
        report = sweep(fake, sweep=True, led=ledger(R7=("open", {"A1": ("task/c", "assigned")})))
        self.assertEqual(fake.done, [])
        self.assertIn("hold branch task/c: lane R7/A1 assigned", report)


class ReviewFixTests(unittest.TestCase):
    def test_fetch_prune_runs_before_remote_branches_are_listed(self):
        fake = BranchFake({}, {"task/m": ["MERGED"]}, remote=["task/m"])
        sweep(fake, go=False, sweep=True)
        self.assertEqual(fake.order, ["refs/heads", "fetch", "refs/remotes/origin"])

    def test_a_stale_tracking_ref_counts_as_deleted_and_is_dropped(self):
        fake = BranchFake({}, {"task/s": ["MERGED"]}, remote=["task/s"])
        fake.stale = {"task/s"}
        report = sweep(fake, sweep=True)
        self.assertIn("deleted remote branch origin/task/s: merged (already gone)", report)
        self.assertIn(["git", "update-ref", "-d", "refs/remotes/origin/task/s"], fake.done)

    def test_a_lease_rejection_is_held_not_deleted(self):
        fake = BranchFake({}, {"task/m": ["MERGED"]}, remote=["task/m"])
        fake.leased = {"task/m"}
        report = sweep(fake, sweep=True)
        self.assertTrue(any(l.startswith("hold remote branch origin/task/m: delete failed")
                            for l in report), report)

    def test_remote_deletes_are_batched(self):
        names = [f"task/b{i}" for i in range(120)]
        fake = BranchFake({}, {n: ["MERGED"] for n in names}, remote=names)
        sweep(fake, sweep=True)
        pushes = [c for c in fake.done if c[:2] == ["git", "push"]]
        self.assertEqual(len(pushes), 3)

    def test_skips_the_base_of_an_open_pr(self):
        fake = BranchFake({}, {"task/base": ["MERGED"], "task/top": ["OPEN"]}, local=["task/base"])
        fake.bases = {"task/top": "task/base"}
        report = sweep(fake, sweep=True)
        self.assertNotIn(["git", "branch", "-D", "task/base"], fake.done)
        self.assertIn("hold branch task/base: base-of-open-pr", report)

    def test_a_closed_rounds_tab_stays_while_its_held_worktree_exists(self):
        path = f"{LANES}/r5-a1"
        meta, pane = tab("t1", "live-repo-r5-a1", path)
        other, po = tab("t2", "live-repo-r5-a2", str(ROOT))
        led = ledger(R5=("closed", {"A1": ("task/a", "merged"), "A2": ("task/b", "merged")}))
        fake = Fake({path: "task/a", f"{LANES}/r5-a2": "task/b"}, {"task/a": ["MERGED"]},
                    tabs=[meta, other], panes=[pane, po], dirty=[path], unpushed=[f"{LANES}/r5-a2"])
        report = sweep(fake, led=led)
        self.assertEqual(fake.done, [])
        self.assertIn("hold tab t1 live-repo-r5-a1: worktree-kept", report)
        self.assertIn("hold tab t2 live-repo-r5-a2: worktree-kept", report)


class PreflightTests(unittest.TestCase):
    def test_a_tree_busy_with_another_process_does_not_block(self):
        fake = BranchFake({f"{LANES}/r5-a1": "task/a"}, {"task/a": ["MERGED"]},
                          busy=[f"{LANES}/r5-a1/sub"])
        led = ledger(R5=("closed", {"A1": ("task/a", "merged")}))
        problems = lc.preflight(
            root=ROOT, prefix="live-repo-", handoff="", run=fake.run, busy=fake.busy, ledger=led
        )
        self.assertEqual(problems, [])

    def test_what_failed_last_go_run_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "failed.json"
            fake = BranchFake({f"{LANES}/r5-a1": "task/a"}, {"task/a": ["MERGED"]})
            fake.remove_out = (1, "fatal: cannot remove")
            led = ledger(R5=("closed", {"A1": ("task/a", "merged")}))
            sweep(fake, led=led, state=state)
            problems = lc.preflight(root=ROOT, prefix="live-repo-", handoff="", run=fake.run,
                                    busy=fake.busy, ledger=led, state=state)
            self.assertEqual(problems, [])
            fake.remove_out = None
            sweep(fake, led=led, state=state)  # a later run that succeeds clears the record
            self.assertEqual(json.loads(state.read_text()), [])

    def test_refuses_while_a_closed_round_has_removable_leftovers(self):
        fake = BranchFake({f"{LANES}/r5-a1": "task/a"}, {"task/a": ["MERGED"]}, local=["task/a"])
        led = ledger(R5=("closed", {"A1": ("task/a", "merged")}))
        problems = lc.preflight(
            root=ROOT, prefix="live-repo-", handoff="", run=fake.run, busy=fake.busy, ledger=led
        )
        self.assertTrue(any("R5" in p and "would remove" in p for p in problems), problems)
        self.assertEqual(fake.done, [])

    def test_passes_when_only_held_or_unmapped_items_remain(self):
        fake = BranchFake(
            {f"{LANES}/r5-a1": "task/a", f"{LANES}/misc": "task/x"},
            {"task/a": ["MERGED"], "task/x": ["MERGED"]},
            dirty=[f"{LANES}/r5-a1"],
        )
        led = ledger(R5=("closed", {"A1": ("task/a", "merged")}))
        problems = lc.preflight(
            root=ROOT, prefix="live-repo-", handoff="", run=fake.run, busy=fake.busy, ledger=led
        )
        self.assertEqual(problems, [])

    def test_an_open_rounds_resolved_lane_tab_does_not_block(self):
        meta, pane = tab("t1", "live-repo-r7-a1", str(ROOT))
        fake = BranchFake({}, {}, tabs=[meta], panes=[pane])
        led = ledger(R7=("open", {"A1": ("task/a", "merged")}))
        problems = lc.preflight(
            root=ROOT, prefix="live-repo-", handoff="", run=fake.run, busy=fake.busy, ledger=led
        )
        self.assertEqual(problems, [])

    def test_fails_closed_when_herdr_or_gh_cannot_answer(self):
        fake = BranchFake({}, {})
        real = fake.run
        fake.run = lambda cmd, timeout=None: (1, "down") if cmd[0] == "herdr" else real(cmd, timeout)
        problems = lc.preflight(
            root=ROOT, prefix="live-repo-", handoff="", run=fake.run, busy=fake.busy, ledger={}
        )
        self.assertTrue(any("herdr" in p for p in problems), problems)


class LedgerLoadTests(unittest.TestCase):
    def test_reads_round_records_and_skips_other_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / ".agent-runs"
            (runs / "R3").mkdir(parents=True)
            (runs / "R3" / "round.json").write_text(json.dumps({"id": "R3", "state": "closed",
                                                                "assignments": {}}))
            (runs / "next").mkdir()
            (runs / "R4").mkdir()
            (runs / "R4" / "round.json").write_text("{broken")
            self.assertEqual(sorted(lc.load_ledger(Path(tmp))), ["R3"])

    def test_summary_counts_actions_and_reasons(self):
        lines = ["hold a (b): dirty", "hold c (d) R5/A1: dirty", "would remove e (f)",
                 "hold tab t1 x: foreign"]
        self.assertEqual(
            lc.summary(lines),
            ["summary: hold dirty=2", "summary: hold tab foreign=1", "summary: would remove=1"],
        )

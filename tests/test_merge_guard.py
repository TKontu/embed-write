"""The merge guard: the only merge path for unattended planners (decision D-002)."""

import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge_guard.py"
spec = importlib.util.spec_from_file_location("merge_guard", SCRIPT)
mg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mg)

HEAD = "a" * 40


class FakeGh:
    """Answers `gh pr view` with a PR record and records every call."""

    def __init__(self, **pr):
        self.pr = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "headRefOid": HEAD,
            "baseRefName": "main",
            "files": [{"path": "experiments/runner.py"}],
            **pr,
        }
        self.calls = []
        self.merged = False

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "view"]:
            pr = dict(self.pr, state="MERGED" if self.merged else self.pr["state"])
            return 0, json.dumps(pr)
        if cmd[:3] == ["gh", "pr", "merge"]:
            self.merged = True
            return 0, ""
        return 1, "unexpected"

    def merge_calls(self):
        return [c for c in self.calls if c[:3] == ["gh", "pr", "merge"]]


class MergeGuardTests(unittest.TestCase):
    def test_merges_the_reviewed_head_and_confirms_the_merge(self):
        gh = FakeGh()
        self.assertEqual(mg.guard(7, HEAD, run=gh), 0)
        [merge] = gh.merge_calls()
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], HEAD)
        self.assertEqual(gh.calls[-1][:3], ["gh", "pr", "view"])  # merge state re-read

    def test_refuses_a_head_that_moved_after_review(self):
        gh = FakeGh(headRefOid="b" * 40)
        self.assertNotEqual(mg.guard(7, HEAD, run=gh), 0)
        self.assertEqual(gh.merge_calls(), [])

    def test_refuses_an_unmergeable_draft_or_closed_pr(self):
        for pr in ({"mergeable": "CONFLICTING"}, {"isDraft": True}, {"state": "CLOSED"}):
            gh = FakeGh(**pr)
            self.assertNotEqual(mg.guard(7, HEAD, run=gh), 0, pr)
            self.assertEqual(gh.merge_calls(), [], pr)

    def test_refuses_a_pr_that_does_not_target_the_default_branch(self):
        gh = FakeGh(baseRefName="feature")
        self.assertNotEqual(mg.guard(7, HEAD, run=gh), 0)
        self.assertEqual(gh.merge_calls(), [])

    def test_leaves_operator_owned_paths_to_the_operator(self):
        for path in (
            "docs/decisions.md",
            "docs/architecture.md",
            ".agent/config.toml",
            ".claude/settings.json",
            "scripts/merge_guard.py",
            "experiments/results/G-01.md",
        ):
            gh = FakeGh(files=[{"path": "experiments/runner.py"}, {"path": path}])
            self.assertNotEqual(mg.guard(7, HEAD, run=gh), 0, path)
            self.assertEqual(gh.merge_calls(), [], path)

    def test_allows_the_results_template_and_ordinary_records(self):
        gh = FakeGh(files=[{"path": "experiments/results/TEMPLATE.md"}, {"path": "docs/todo.md"}])
        self.assertEqual(mg.guard(7, HEAD, run=gh), 0)

    def test_requires_a_full_head_sha(self):
        self.assertNotEqual(mg.guard(7, "abc123", run=FakeGh()), 0)


if __name__ == "__main__":
    unittest.main()

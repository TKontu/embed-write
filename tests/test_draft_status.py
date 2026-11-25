"""AD-07: draft status stays "draft" until an explicit expert ReviewAction (I5). Synthetic text."""

import dataclasses
import re
import tempfile
import unittest
from pathlib import Path

from service.draft_assembly import assemble_draft
from service.draft_status import DRAFT, REVIEWED, ReviewAction, mark_reviewed

REPO = Path(__file__).resolve().parent.parent
ALLOWED = Path("service") / "draft_status.py"
_EXCLUDE = {"tests", ".venv", ".git", "node_modules", "__pycache__"}
_PATTERNS = (
    re.compile(r"""status\s*=\s*["']reviewed["']"""),
    re.compile(r"""status\s*=\s*(?:[\w.]+\.)?REVIEWED\b"""),
)


def find_reviewed_assignments(root: Path) -> list[str]:
    """Return relative paths of *.py files under top-level package dirs assigning status reviewed."""
    hits = []
    for top in sorted(p for p in root.iterdir() if p.is_dir()):
        if top.name in _EXCLUDE or top.name.startswith("."):
            continue
        for path in sorted(top.rglob("*.py")):
            rel = path.relative_to(root)
            if any(part in _EXCLUDE for part in rel.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(p.search(text) for p in _PATTERNS):
                hits.append(str(rel))
    return hits


def _draft():
    return assemble_draft([("Findings", [("claim", "Synthetic block text.")])])


class DraftStatusTest(unittest.TestCase):
    def test_assembled_draft_is_draft(self):
        self.assertEqual(_draft().status, DRAFT)
        self.assertEqual(DRAFT, "draft")
        self.assertEqual(REVIEWED, "reviewed")

    def test_mark_reviewed_with_confirmed_action(self):
        draft = _draft()
        out = mark_reviewed(draft, ReviewAction(user_id="expert-1", confirmed=True))
        self.assertEqual(out.status, REVIEWED)
        self.assertEqual(draft.status, DRAFT)
        self.assertEqual(out.markdown, draft.markdown)
        self.assertEqual(out.blocks, draft.blocks)

    def test_review_action_is_frozen(self):
        action = ReviewAction(user_id="u", confirmed=True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            action.confirmed = False

    def test_invalid_actions_raise(self):
        draft = _draft()
        for bad in (None, "u", {"user_id": "u", "confirmed": True}):
            with self.assertRaises(TypeError):
                mark_reviewed(draft, bad)
        for action in (
            ReviewAction(user_id="u", confirmed=False),
            ReviewAction(user_id="", confirmed=True),
            ReviewAction(user_id="   ", confirmed=True),
            ReviewAction(user_id="u", confirmed=1),
        ):
            with self.assertRaises(ValueError):
                mark_reviewed(draft, action)
        self.assertEqual(draft.status, DRAFT)

    def test_remarking_reviewed_raises(self):
        out = mark_reviewed(_draft(), ReviewAction(user_id="u", confirmed=True))
        with self.assertRaises(ValueError):
            mark_reviewed(out, ReviewAction(user_id="u", confirmed=True))


class StaticGuardTest(unittest.TestCase):
    def test_only_draft_status_assigns_reviewed(self):
        self.assertEqual(find_reviewed_assignments(REPO), [str(ALLOWED)])

    def test_scanner_detects_planted_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for d in ("service", "editlog", "tests", ".venv"):
                (root / d).mkdir()
            (root / "service" / "ok.py").write_text('status = "draft"\n')
            (root / "editlog" / "bad.py").write_text('x = f(status="reviewed")\n')
            (root / "service" / "bad2.py").write_text("d = replace(d, status=draft_status.REVIEWED)\n")
            (root / "tests" / "t.py").write_text('status="reviewed"\n')
            (root / ".venv" / "v.py").write_text('status="reviewed"\n')
            self.assertEqual(
                find_reviewed_assignments(root),
                [str(Path("editlog/bad.py")), str(Path("service/bad2.py"))],
            )


if __name__ == "__main__":
    unittest.main()

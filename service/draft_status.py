"""Draft status (AD-07): a draft stays ``"draft"`` until the expert marks it reviewed (I5).

``ReviewAction`` records an explicit expert action in the UI; constructing one is the only way to
authorize a status change. ``mark_reviewed`` validates it and returns a new ``AssembledDraft`` with
status ``"reviewed"``; the input draft is never mutated. No other module may assign the reviewed
status (guarded by tests/test_draft_status.py). Runs locally only (I9); O(1).

Unwired by design until AD-08 (review flow: the expert's explicit "mark reviewed" action).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from service.draft_assembly import AssembledDraft

DRAFT = "draft"
REVIEWED = "reviewed"


@dataclass(frozen=True)
class ReviewAction:
    user_id: str
    confirmed: bool


def mark_reviewed(draft: AssembledDraft, action: ReviewAction) -> AssembledDraft:
    if not isinstance(action, ReviewAction):
        raise TypeError(f"action must be a ReviewAction, got {type(action).__name__}")
    if not isinstance(action.user_id, str) or not action.user_id.strip():
        raise ValueError("review action has no user_id")
    if action.confirmed is not True:
        raise ValueError("review action is not confirmed")
    if draft.status != DRAFT:
        raise ValueError(f"draft status is {draft.status!r}, expected {DRAFT!r}")
    return dataclasses.replace(draft, status=REVIEWED)

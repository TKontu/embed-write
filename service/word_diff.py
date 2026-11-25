"""Word-level diff (UX-01): the data a diff-first proposal view renders.

``word_diff`` compares an original passage with one candidate and returns an
ordered tuple of frozen ``DiffOp`` rows. Each row carries its ``kind``
(``equal``, ``delete``, ``insert`` or ``replace``) plus the text it covers on
each side, so a view can render the change before any accept (invariant I5: no
edit is applied without a user action on a visible diff). This module only
computes data: it applies nothing, stores nothing and judges nothing.

Tokens are words with their trailing whitespace attached (``\\S+\\s*``), so
joining every row's ``original_text`` reproduces the original exactly and
joining every row's ``candidate_text`` reproduces the candidate exactly.
Leading whitespace has no preceding word and becomes its own first token; a
whitespace-only text is one token. Changing only a word's trailing whitespace
therefore shows up as a ``replace`` of that word rather than a separate
whitespace row.

Matching is ``difflib.SequenceMatcher(autojunk=False)`` over the token lists,
and its opcodes already alternate ``equal`` with non-``equal`` runs, so
adjacent rows never share a kind. ``proposal_diffs`` maps the same diff over
``generation.propose.Proposal.candidates`` (a ``tuple[str, ...]``), one diff per
candidate in input order.

Unwired by design until the UX-01 UI. One passage pair per call; there is no
length cap (``SequenceMatcher`` is quadratic in tokens in the worst case).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Sequence

_TOKEN_RE = re.compile(r"\S+\s*")

DIFF_KINDS = ("equal", "delete", "insert", "replace")


@dataclass(frozen=True)
class DiffOp:
    """One diff row: what it covers on the original and on the candidate side."""

    kind: str
    original_text: str
    candidate_text: str


def _tokenize(text: str) -> list[str]:
    """Split ``text`` into word-plus-trailing-whitespace tokens covering it."""
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return [text] if text else []
    covered = len("".join(tokens))
    leading = text[: len(text) - covered]
    if leading:
        tokens.insert(0, leading)
    return tokens


def word_diff(original: str, candidate: str) -> tuple[DiffOp, ...]:
    """Return the word-level diff rows turning ``original`` into ``candidate``."""
    original_tokens = _tokenize(original)
    candidate_tokens = _tokenize(candidate)
    matcher = difflib.SequenceMatcher(
        None, original_tokens, candidate_tokens, autojunk=False)
    return tuple(
        DiffOp(kind, "".join(original_tokens[i1:i2]),
               "".join(candidate_tokens[j1:j2]))
        for kind, i1, i2, j1, j2 in matcher.get_opcodes()
    )


def proposal_diffs(
    original: str, candidates: Sequence[str],
) -> tuple[tuple[DiffOp, ...], ...]:
    """Diff ``original`` against each candidate, keeping the candidates' order."""
    return tuple(word_diff(original, candidate) for candidate in candidates)

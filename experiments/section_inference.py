"""CO-14: provisional section inference for documents without ATX headings (D-015).

``infer_sections(markdown)`` returns ``[{"start_line", "level", "title_line", "inferred": True,
"method"}]`` with 0-based line numbers into the unchanged source text (I1: never rewritten).

Methods (deterministic, offline, stdlib only):

* ``numbering``: a standalone line (blank or document edge before and after), <= 80 chars, no
  terminal sentence punctuation, starting with a section number (``1.``, ``2.3``, ``IV.``,
  ``A)``). Level = number depth (``2.3`` -> 2). Consecutive numbered lines are a list, never
  headings (they are not standalone).
* ``formatting``: a standalone line that is entirely bold (``**...**``/``__...__``), or short
  (<= 80 chars) with no terminal punctuation, followed by a prose paragraph (a
  line that is not itself title-like). Level 1.

Lines in fenced code (annotation_sample fence helpers) or top-level indented code never qualify,
nor do list items, table rows, block quotes or ATX lines. Memory O(lines) per document.

Production caller: experiments.intake ``sections`` step. Its OUT/sections.json consumer is
unwired by design (CO-14 follow-up: sampling strata, demo provisional display).
"""
from __future__ import annotations

import re

from experiments.annotation_sample import _fence_close, _fence_left, _fence_open, _indent

MAX_TITLE = 80
_NUMBER = re.compile(r"^(?:(\d+(?:\.\d+)*)\.?|([IVXLC]+)\.|([A-Z])[.)])[ \t]+\S")
_BOLD = re.compile(r"^(\*\*|__)(?=\S)(.+?)(?<=\S)\1$")
_TERMINAL = (".", "!", "?", ":", ";", ",")
_NOT_PROSE = re.compile(r"^\s*(?:[-*+][ \t]|\d+[.)][ \t]|>|\||#{1,6}(?:[ \t]|$))")


def _code_lines(lines: list[str]) -> set[int]:
    """Indices of lines inside fenced code (fence lines included) or top-level indented code."""
    code: set[int] = set()
    fence = None
    cols: list[int] = []
    prev_blank = True
    for i, line in enumerate(lines):
        if fence and _fence_left(line, fence):
            fence = None
        if fence:
            code.add(i)
            if _fence_close(line, fence):
                fence = None
            prev_blank = False
            continue
        m, depth, col, cols = _fence_open(line, cols)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)), depth, col)
            code.add(i)
        elif line.strip() and not cols and prev_blank and _indent(line) >= 4:
            code.add(i)
            continue  # stays "prev_blank" so a following indented line is code too
        prev_blank = not line.strip()
    return code


def _level(m: re.Match) -> int:
    return m.group(1).count(".") + 1 if m.group(1) else 1


def _title_like(raw: str) -> bool:
    line = raw.strip()
    return bool(_BOLD.match(line)) or (len(line) <= MAX_TITLE and not line.endswith(_TERMINAL))


def infer_sections(markdown: str) -> list[dict]:
    lines = markdown.splitlines()
    code = _code_lines(lines)
    n = len(lines)

    def blank(i: int) -> bool:
        return i < 0 or i >= n or not lines[i].strip()

    def prose(i: int) -> bool:
        return 0 <= i < n and bool(lines[i].strip()) and i not in code \
            and not _NOT_PROSE.match(lines[i])

    out = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or i in code or not (blank(i - 1) and blank(i + 1)):
            continue
        short = len(line) <= MAX_TITLE and not line.endswith(_TERMINAL)
        num = _NUMBER.match(line)
        if num and short:
            method, level = "numbering", _level(num)
        elif _NOT_PROSE.match(raw) or line.startswith(("```", "~~~")):
            continue
        elif _BOLD.match(line) or short:
            nxt = i + 2
            while nxt < n and not lines[nxt].strip():
                nxt += 1
            if not prose(nxt) or _NUMBER.match(lines[nxt].strip()) or _title_like(lines[nxt]):
                continue  # a paragraph must follow, not another title-like line
            method, level = "formatting", 1
        else:
            continue
        out.append({"start_line": i, "level": level, "title_line": i, "inferred": True,
                    "method": method})
    return out

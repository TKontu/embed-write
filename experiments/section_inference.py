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

* ``topic_shift`` (fallback, only when the two above find nothing): TextTiling-style lexical
  cohesion. Paragraphs are blank-line blocks of non-code lines. Each gap between paragraphs is
  scored by bag-of-words cosine between the ``WINDOW`` paragraphs before and after it
  (lowercased ``\w+`` tokens of >= 3 chars, minus a small stopword list); its depth is the
  climb to the nearest similarity peak on each side. Gaps with depth >= ``MIN_DEPTH`` and >=
  mean - sd/2 of all depths become boundaries, deepest first, keeping every section >=
  ``MIN_SECTION`` paragraphs. Documents with < ``MIN_PARAGRAPHS`` paragraphs yield none. When
  any boundary is found the first paragraph also starts a section. ``title_line`` None, level 1.
  Limits: lexical only (synonyms/paraphrase invisible); constants untuned on real text.

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


MIN_PARAGRAPHS = 6  # fewer paragraphs: too little text to compare windows
MIN_SECTION = 2  # paragraphs per topic_shift section
WINDOW = 2  # paragraphs on each side of a gap
MIN_DEPTH = 0.5  # absolute depth floor (sum of both climbs); synthetic single-topic text
# peaks at ~0.4, synthetic topic changes at >= 0.6. Untuned on real text.
_WORD = re.compile(r"[^\W\d_]{3,}")
_STOP = frozenset("""the and for are but not you all any can had her was one our out has his how
its may new now see two who did get him let say she too use this that with from have they will
what when where which while into than then them there these those their been being were would
could should about after before also each other over such only very more most some same own
just because between through during under again further here both few nor off once""".split())


def _paragraphs(lines: list[str], code: set[int]) -> list[tuple[int, dict[str, int]]]:
    paras: list[tuple[int, dict[str, int]]] = []
    cur = None
    for i, line in enumerate(lines):
        if not line.strip() or i in code:
            cur = None
            continue
        if cur is None:
            cur = {}
            paras.append((i, cur))
        for w in _WORD.findall(line.lower()):
            if w not in _STOP:
                cur[w] = cur.get(w, 0) + 1
    return paras


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _merge(bags: list[dict[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for bag in bags:
        for k, v in bag.items():
            out[k] = out.get(k, 0) + v
    return out


def _topic_shift(lines: list[str], code: set[int]) -> list[dict]:
    paras = _paragraphs(lines, code)
    n = len(paras)
    if n < MIN_PARAGRAPHS:
        return []
    bags = [b for _, b in paras]
    sims = [_cosine(_merge(bags[max(0, g - WINDOW):g]), _merge(bags[g:g + WINDOW]))
            for g in range(1, n)]  # sims[k] = gap before paragraph k + 1
    depths = []
    for k, s in enumerate(sims):
        left = s
        for j in range(k - 1, -1, -1):
            if sims[j] < left:
                break
            left = sims[j]
        right = s
        for j in range(k + 1, len(sims)):
            if sims[j] < right:
                break
            right = sims[j]
        depths.append((left - s) + (right - s))
    mean = sum(depths) / len(depths)
    sd = (sum((d - mean) ** 2 for d in depths) / len(depths)) ** 0.5
    cut = max(MIN_DEPTH, mean - sd / 2)
    chosen: list[int] = []  # paragraph indices that start a new section
    for d, k in sorted(((d, k) for k, d in enumerate(depths)), key=lambda t: (-t[0], t[1])):
        p = k + 1
        if d < cut or p < MIN_SECTION or n - p < MIN_SECTION:
            continue
        if all(abs(p - q) >= MIN_SECTION for q in chosen):
            chosen.append(p)
    if not chosen:
        return []
    return [{"start_line": paras[p][0], "level": 1, "title_line": None, "inferred": True,
             "method": "topic_shift"} for p in [0] + sorted(chosen)]


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
    return out or _topic_shift(lines, code)

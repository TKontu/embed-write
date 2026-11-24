"""Length delta (VF-06): reported, not judged.

``length_delta`` counts words and characters in an original passage and a candidate and reports
their signed differences and candidate/original ratios. Pure reporting: no threshold, verdict or
score, and no combination with other verification axes (VF-10).

- Words are matches of ``WORD_RE`` (``\\w+(?:[-'’]\\w+)*``), so Markdown punctuation such as
  ``#``, ``*``, ``>`` or a lone ``-`` is not a word, while ``well-known`` and ``don't`` are one.
- Characters are code points after stripping surrounding whitespace (inner whitespace counts).
- A ratio is ``None`` when the original count is zero.

Unwired by design until VF-07 (the verification panel) calls it. Linear in text length; one pair.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WORD_RE = re.compile(r"\w+(?:[-'’]\w+)*")


def count_words(text: str) -> int:
    return sum(1 for _ in WORD_RE.finditer(text))


def count_chars(text: str) -> int:
    return len(text.strip())


def _ratio(candidate: int, original: int) -> float | None:
    return candidate / original if original else None


@dataclass(frozen=True)
class LengthDelta:
    original_words: int
    candidate_words: int
    word_delta: int
    word_ratio: float | None
    original_chars: int
    candidate_chars: int
    char_delta: int
    char_ratio: float | None


def length_delta(original: str, candidate: str) -> LengthDelta:
    ow, cw = count_words(original), count_words(candidate)
    oc, cc = count_chars(original), count_chars(candidate)
    return LengthDelta(
        original_words=ow,
        candidate_words=cw,
        word_delta=cw - ow,
        word_ratio=_ratio(cw, ow),
        original_chars=oc,
        candidate_chars=cc,
        char_delta=cc - oc,
        char_ratio=_ratio(cc, oc),
    )

"""Register profile surface features (RG-04, G-06; docs/architecture.md 5.4 item 4, 5.6).

Deterministic, stdlib-only, English-only feature report of what distinguishes two
sentence sets (A = corpus, B = baseline-LLM). Per sentence it counts words, hedges,
passive constructions, numbers and connectives; ``compare`` reports, per feature
and side by side, n / mean / median for each set, the difference of means (B minus
A) and Cohen's d with pooled SD (None when undefined). There is deliberately no
verdict, threshold or combined score; ``sorted_by_effect`` orders by |d| for
display only.

Heuristics (residuals): hedges and connectives use the fixed lexicons below;
passive voice is a heuristic -- a form of "be", optionally one adverb, then a past
participle (regular ``-ed`` or the fixed irregular list) -- so it misses
get-passives and misfires on adjectival -ed forms. Numbers reuse
``analysis.numbers.extract_quantities`` (digits, decimals, percent, units).

Scale: ``compare`` consumes iterables once and keeps only one float list per
feature per set (O(n) floats, needed for the median); sentences are not held.

Connections: unwired by design until RG-05 (register-fit signal) and the slow
layer's explanations consume the report.
"""
from __future__ import annotations

import math
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from analysis.numbers import extract_quantities

FEATURES = ("words", "hedges", "passive", "numbers", "connectives")

HEDGES = frozenset({
    "may", "might", "could", "possibly", "perhaps", "likely", "unlikely",
    "probably", "suggest", "suggests", "suggested", "appear", "appears",
    "appeared", "seem", "seems", "seemed", "approximately", "roughly",
    "apparently", "presumably", "potentially", "somewhat", "arguably",
    "indicate", "indicates", "tend", "tends",
})

CONNECTIVES = (
    "however", "therefore", "moreover", "furthermore", "thus", "hence",
    "consequently", "nevertheless", "nonetheless", "meanwhile", "additionally",
    "in addition", "as a result", "on the other hand", "in contrast",
    "for example", "for instance", "in particular", "in summary", "in conclusion",
)

BE_FORMS = frozenset({"am", "is", "are", "was", "were", "be", "been", "being"})

IRREGULAR_PARTICIPLES = frozenset({
    "written", "given", "taken", "made", "done", "seen", "known", "shown",
    "found", "built", "held", "kept", "left", "led", "paid", "said", "sent",
    "set", "put", "brought", "bought", "thought", "taught", "caught", "told",
    "sold", "chosen", "driven", "eaten", "fallen", "forgotten", "frozen",
    "hidden", "broken", "spoken", "stolen", "drawn", "grown", "thrown", "worn",
    "begun", "run", "won", "understood", "read", "met", "cut", "hit", "lost",
    "spent", "meant", "felt", "heard", "born", "seen", "become",
})

_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:[.,]\d+)*%?")
_ALPHA = re.compile(r"[a-z]+")
_CONNECTIVE = re.compile(
    r"\b(?:" + "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in
                         sorted(CONNECTIVES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _is_participle(word: str) -> bool:
    return word in IRREGULAR_PARTICIPLES or (len(word) > 3 and word.endswith("ed"))


def _passive_count(tokens: list[str]) -> int:
    count = 0
    for i, tok in enumerate(tokens):
        if tok not in BE_FORMS:
            continue
        nxt = tokens[i + 1:i + 3]
        if nxt and _is_participle(nxt[0]):
            count += 1
        elif len(nxt) == 2 and nxt[0].endswith("ly") and _is_participle(nxt[1]):
            count += 1
    return count


def sentence_features(sentence: str) -> dict[str, int]:
    """Return the per-sentence counts for every name in ``FEATURES``."""
    lowered = sentence.lower()
    alpha = _ALPHA.findall(lowered)
    return {
        "words": len(_WORD.findall(sentence)),
        "hedges": sum(1 for w in alpha if w in HEDGES),
        "passive": _passive_count(alpha),
        "numbers": len(extract_quantities(sentence)),
        "connectives": len(_CONNECTIVE.findall(sentence)),
    }


@dataclass(frozen=True)
class SetSummary:
    n: int
    mean: float | None
    median: float | None


@dataclass(frozen=True)
class FeatureComparison:
    name: str
    a: SetSummary
    b: SetSummary
    mean_diff: float | None  # B minus A
    cohens_d: float | None   # pooled SD; None when undefined


@dataclass(frozen=True)
class FeatureReport:
    features: tuple[FeatureComparison, ...]

    def feature(self, name: str) -> FeatureComparison:
        for comp in self.features:
            if comp.name == name:
                return comp
        raise KeyError(name)

    def sorted_by_effect(self) -> list[FeatureComparison]:
        """Display order by |d| descending; undefined d last. Not a ranking claim."""
        return sorted(self.features,
                      key=lambda c: (c.cohens_d is None, -abs(c.cohens_d or 0.0)))


def _summary(values: list[float]) -> SetSummary:
    if not values:
        return SetSummary(0, None, None)
    return SetSummary(len(values), statistics.fmean(values), statistics.median(values))


def _cohens_d(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    pooled = ((len(a) - 1) * statistics.variance(a)
              + (len(b) - 1) * statistics.variance(b)) / (len(a) + len(b) - 2)
    if pooled <= 0:
        return None
    return (statistics.fmean(b) - statistics.fmean(a)) / math.sqrt(pooled)


def _collect(sentences: Iterable[str]) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {name: [] for name in FEATURES}
    for sentence in sentences:
        for name, count in sentence_features(sentence).items():
            values[name].append(float(count))
    return values


def compare(set_a: Iterable[str], set_b: Iterable[str]) -> FeatureReport:
    """Side-by-side feature report of set B (baseline-LLM) against set A (corpus)."""
    va, vb = _collect(set_a), _collect(set_b)
    comps = []
    for name in FEATURES:
        sa, sb = _summary(va[name]), _summary(vb[name])
        diff = None if sa.mean is None or sb.mean is None else sb.mean - sa.mean
        comps.append(FeatureComparison(name, sa, sb, diff, _cohens_d(va[name], vb[name])))
    return FeatureReport(tuple(comps))

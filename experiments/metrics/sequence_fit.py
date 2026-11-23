"""Sequence-fit scorer for G-05.2 (docs/todo-01-experiments.md).

Scores analysis.detectors.Detectors against analysis.perturb ground truth:
precision/recall of flags on perturbed sections, and false flags on
unperturbed reports counted per document_id. Pure stdlib; move labels only.

Unwired by design until the G-05 runner (todo-01 G-05.2) calls score() on
the held-out split. No threshold verdict here (G-05.4). Both iterables are
streamed; memory is O(distinct unperturbed document ids).
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from analysis.detectors import FOREIGN, MISSING, OUT_OF_ORDER
from analysis.perturb import DELETE, INSERT, SWAP, Perturbation
from analysis.transitions import LabelledSection


def _flags(p: Perturbation, finding) -> bool:
    if finding.section_type != p.section_type:
        return False
    if p.kind == DELETE:
        return finding.kind == MISSING and finding.move == p.move
    if p.kind == INSERT:
        return finding.kind == FOREIGN and finding.move == p.move
    if p.kind == SWAP:
        if finding.kind != OUT_OF_ORDER:
            return False
        i, j = p.positions
        swapped = {p.original[i], p.original[j]}
        return bool(swapped & set(finding.move.split('->')))
    raise ValueError(f'unknown perturbation kind {p.kind!r}')


def match(p: Perturbation, findings) -> bool:
    """True iff some finding detects perturbation p."""
    return any(_flags(p, f) for f in findings)


@dataclass(frozen=True)
class FitScore:
    perturbations: int
    detected: int
    flags_on_perturbed: int
    true_flags: int
    precision: float | None
    recall: float | None
    unperturbed_reports: int
    false_flags_unperturbed: int
    max_false_flags_per_report: int


def score(perturbed: Iterable[tuple[LabelledSection, Perturbation]],
          unperturbed: Iterable[LabelledSection], detectors) -> FitScore:
    n = detected = flags = true = 0
    for section, p in perturbed:
        findings = detectors.detect(section)
        n += 1
        hits = sum(1 for f in findings if _flags(p, f))
        flags += len(findings)
        true += hits
        detected += hits > 0
    per_report = {}
    for section in unperturbed:
        count = len(detectors.detect(section))
        doc = section.document_id
        per_report[doc] = per_report.get(doc, 0) + count
    return FitScore(
        perturbations=n, detected=detected, flags_on_perturbed=flags,
        true_flags=true, precision=true / flags if flags else None,
        recall=detected / n if n else None,
        unperturbed_reports=len(per_report),
        false_flags_unperturbed=sum(per_report.values()),
        max_false_flags_per_report=max(per_report.values(), default=0))


def to_record(s: FitScore) -> dict:
    return asdict(s)

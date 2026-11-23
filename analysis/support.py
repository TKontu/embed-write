"""Support filtering for sequence detector findings (SQ-04, I2).

A pattern seen in a handful of reports is not a rule: a Finding from
analysis.detectors is kept only when the corpus support behind the rule it
relies on reaches min_support; otherwise it is suppressed (kept aside, not
dropped).

Support per kind, read from Finding.evidence:
- missing      -> documents_with (documents showing the expected move);
- foreign      -> section_count  (sections establishing the type's moves);
- out_of_order -> section_count  (sections establishing the transitions).

Pure stdlib. Streams the iterable once; O(findings).

Unwired by design until the sequence-fit overlay (todo-05) calls it.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from analysis.detectors import FOREIGN, MISSING, OUT_OF_ORDER, Finding

_SUPPORT_KEY = {
    MISSING: 'documents_with',
    FOREIGN: 'section_count',
    OUT_OF_ORDER: 'section_count',
}


def support_of(finding: Finding) -> int:
    if not isinstance(finding, Finding):
        raise TypeError(f'expected Finding, got {type(finding).__name__}')
    key = _SUPPORT_KEY.get(finding.kind)
    if key is None:
        raise ValueError(f'unknown finding kind: {finding.kind!r}')
    evidence = dict(finding.evidence)
    if key not in evidence:
        raise ValueError(f'{finding.kind} evidence lacks {key!r}')
    return evidence[key]


@dataclass(frozen=True)
class SupportedFindings:
    kept: tuple
    suppressed: tuple


def filter_supported(findings: Iterable[Finding], *,
                     min_support: int = 5) -> SupportedFindings:
    if isinstance(min_support, bool) or not isinstance(min_support, int):
        raise ValueError('min_support must be an int')
    if min_support < 1:
        raise ValueError('require min_support >= 1')
    kept, suppressed = [], []
    for finding in findings:
        (kept if support_of(finding) >= min_support
         else suppressed).append(finding)
    return SupportedFindings(tuple(kept), tuple(suppressed))

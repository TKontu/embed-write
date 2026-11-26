"""RD-03 per-document redundancy suppression: the expert marks a pair as intentional.

Append-only JSON Lines (UTF-8, one object per line):
{"document": str, "first": str, "second": str}. A mark applies to one document only
and matches the pair regardless of order; duplicate marks are idempotent on read.

Unwired by design until the G-04 redundancy overlay / RD-02 consume it.
Scale: reading is streamed line by line; memory O(marks for one document).
Residual: single writer only; no file locking, no un-marking.
"""

import json
from typing import Iterable

from analysis.redundancy import RedundantPair

_FIELDS = ('document', 'first', 'second')


def _validate(document, first, second):
    for name, value in zip(_FIELDS, (document, first, second)):
        if not isinstance(value, str) or not value:
            raise ValueError(f'{name} must be a non-empty str')
    if first == second:
        raise ValueError('first and second must differ')


class SuppressionStore:
    def __init__(self, path):
        self.path = path

    def mark(self, document, first, second):
        """Validate, then append one full line and flush. Nothing is written on ValueError."""
        _validate(document, first, second)
        record = {'document': document, 'first': first, 'second': second}
        line = json.dumps(record, ensure_ascii=False) + '\n'
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write(line)
            fh.flush()

    def suppressed(self, document):
        """Return the document's marked pairs as a frozenset of unordered frozenset pairs."""
        _validate(document, 'a', 'b')
        try:
            fh = open(self.path, encoding='utf-8')
        except FileNotFoundError:
            return frozenset()
        pairs = set()
        with fh:
            for lineno, line in enumerate(fh, start=1):
                try:
                    if not line.endswith('\n'):
                        raise ValueError('truncated (no newline)')
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError('not a JSON object')
                    _validate(*(record.get(k) for k in _FIELDS))
                except ValueError as exc:
                    raise ValueError(
                        f'{self.path}: line {lineno}: malformed record: {exc}') from None
                if record['document'] == document:
                    pairs.add(frozenset((record['first'], record['second'])))
        return frozenset(pairs)


def filter_suppressed(pairs: Iterable[RedundantPair],
                      suppressed: frozenset) -> tuple[RedundantPair, ...]:
    """Drop pairs whose unordered {first, second} was marked; preserve input order."""
    return tuple(p for p in pairs if frozenset((p.first, p.second)) not in suppressed)

"""Document-level split enforcement for EV-05.

Unwired by design: G-01.5, G-03.3 and G-04.1 gate modules will call this
through the runner. Only document ids are retained, never corpus text.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable


class SplitLeakError(Exception):
    """Evaluation encountered a training or unassigned document."""


@dataclass(frozen=True, init=False)
class DocumentSplit:
    """Immutable id sets; construction uses O(number of documents) memory."""

    train_ids: frozenset[str]
    test_ids: frozenset[str]

    def __init__(self, train_ids: Iterable[str], test_ids: Iterable[str]):
        train = frozenset(train_ids)
        test = frozenset(test_ids)
        if not test:
            raise ValueError("test_ids must not be empty")
        if not train.isdisjoint(test):
            raise ValueError("train_ids and test_ids must not overlap")
        object.__setattr__(self, "train_ids", train)
        object.__setattr__(self, "test_ids", test)

    def check_eval(self, doc_ids: Iterable[str]) -> None:
        """Validate ids in order, using O(1) extra memory; stop at first violation."""
        for doc_id in doc_ids:
            if doc_id in self.train_ids:
                raise SplitLeakError(f"Training document evaluated: {doc_id!r}")
            if doc_id not in self.test_ids:
                raise SplitLeakError(f"Unassigned document evaluated: {doc_id!r}")


def split_documents(
    doc_ids: Iterable[str], test_fraction: float, seed: int
) -> DocumentSplit:
    """Split unique string ids independently of input order using a local RNG.

    The fraction must be strictly between zero and one. The test count is
    floor(unique count * fraction), with a minimum of one. A singleton therefore
    has no training documents. Duplicate ids count once; empty input is invalid.
    Sorting and shuffling retain O(document count) ids, never document contents.
    """
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be strictly between zero and one")
    ids = sorted(set(doc_ids))
    if not ids:
        raise ValueError("doc_ids must not be empty")
    random.Random(seed).shuffle(ids)
    test_count = max(1, int(len(ids) * test_fraction))
    return DocumentSplit(ids[test_count:], ids[:test_count])

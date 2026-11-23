"""Check local embedding repeatability; no model loading or network access.

Unwired by design until EM-02 runs it on each candidate model. Callers supply
bounded text sequences. Retains the baseline and one current vector list,
plus O(n) reversed input references; memory does not grow with run count.
"""

from collections.abc import Sequence

from service.embedder import Embedder, EmbedderError, embed
from service.vectors import Level


class DeterminismError(EmbedderError):
    """An embedder changed its output for the same input."""


def check_determinism(embedder: Embedder, texts: Sequence[str], level: Level,
                      runs: int = 3, batch_size: int | None = None) -> None:
    """Compare repeat, reversed-order and optional singleton-batch runs.

    Uses exact float tuple equality (no tolerance), matching level and dims.
    Input indices are zero-based and runs are one-based, including baseline
    run 1. Malformed backend results and input errors propagate from embed.
    This checks only the current in-process backend, not fresh model loads.
    """
    if runs < 2:
        raise ValueError('runs must be at least 2')
    if type(runs) is not int:
        raise TypeError('runs must be an integer')
    options = {} if batch_size is None else {'batch_size': batch_size}
    baseline = embed(embedder, texts, level, **options)

    def compare(current, run, description):
        for index, (expected, actual) in enumerate(zip(baseline, current)):
            if (expected.level is not actual.level
                    or len(expected.values) != len(actual.values)
                    or expected.values != actual.values):
                identity = ', '.join(
                    f'{name}={getattr(embedder, name)!r}'
                    for name in ('model_id', 'model_version')
                    if hasattr(embedder, name)
                )
                suffix = f' ({identity})' if identity else ''
                raise DeterminismError(
                    f'Determinism mismatch at input index {index}, '
                    f'run {run} ({description}){suffix}'
                )

    for run in range(2, runs + 1):
        compare(embed(embedder, texts, level, **options), run, 'repeated')
    reversed_vectors = embed(embedder, texts[::-1], level, **options)
    reversed_vectors.reverse()
    compare(reversed_vectors, runs + 1, 'reversed')
    del reversed_vectors
    if batch_size is not None:
        compare(embed(embedder, texts, level, batch_size=1),
                runs + 2, 'batch_size=1')

"""Blind-pair preference; unwired by design until BJ/G-xx gate reporting.

Inputs are choices, not claims about who supplied the judgments. Report the
returned sample size alongside the estimate and bootstrap interval (ST-02).
"""


import random


def win_rate(choices):
    """Return arm A's win rate, giving each tie half credit."""
    wins = choices.count('a')
    losses = choices.count('b')
    ties = choices.count('tie')
    n = len(choices)
    if not n or wins + losses + ties != n:
        raise ValueError("Expected a nonempty sequence of a, b, or tie")
    return dict(win_rate=(wins + ties / 2) / n, n=n,
                wins=wins, losses=losses, ties=ties)


def bootstrap_interval(choices, n_resamples=10000, confidence=0.95, seed=0):
    """Return equal-tail percentile bounds using linear rank interpolation.

    Each replicate draws n independent choices with replacement. Categories
    are sampled from counts, without copying replicate lists. A histogram of
    half-win totals uses O(n) auxiliary memory, independent of n_resamples;
    runtime is O(n * n_resamples). No corpus or external data is loaded.
    """
    stats = win_rate(choices)
    if n_resamples < 1:
        raise ValueError('n_resamples must be positive')
    if not 0 < confidence < 1:
        raise ValueError('confidence must be between zero and one')
    n = stats['n']
    wins = stats['wins']
    losses_end = wins + stats['losses']
    rng = random.Random(seed)
    histogram = [0] * (2 * n + 1)
    for _ in range(n_resamples):
        total = 0
        for _ in range(n):
            draw = rng.randrange(n)
            if draw < wins:
                total += 2
            elif draw >= losses_end:
                total += 1
        histogram[total] += 1

    def percentile(probability):
        rank = probability * (n_resamples - 1)
        lower = int(rank)
        upper = min(lower + 1, n_resamples - 1)
        cumulative = 0
        lower_value = None
        for total, count in enumerate(histogram):
            cumulative += count
            if lower_value is None and cumulative > lower:
                lower_value = total
            if cumulative > upper:
                return (lower_value + (rank - lower) * (total - lower_value)) / (2 * n)

    tail = (1 - confidence) / 2
    return percentile(tail), percentile(1 - tail)

"""Calibration metrics for MT-02; unwired by design until the G-01 gate.

The future move-classifier gate module is the intended production caller.
Inputs are sized sequences; each is traversed once, with O(n_bins) memory.
"""


def reliability_bins(confidences, correct, n_bins=10):
    """Return equal-width, left-closed bins (the final bin includes 1).

    Empty bins have None means. Confidence values must lie in [0, 1] and
    correctness values must be bools or 0/1. Invalid values, empty or unequal
    sequences, and nonpositive/noninteger bin counts raise ValueError.
    """
    if not isinstance(n_bins, int) or n_bins < 1:
        raise ValueError("n_bins must be a positive integer")
    if len(confidences) != len(correct) or not len(confidences):
        raise ValueError("inputs must have equal, nonzero lengths")
    bins = [dict(lo=i / n_bins, hi=(i + 1) / n_bins, count=0,
                 mean_confidence=None, accuracy=None) for i in range(n_bins)]
    confidence_sums = [0.0] * n_bins
    correct_sums = [0] * n_bins
    for confidence, outcome in zip(confidences, correct):
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if outcome not in (0, 1):
            raise ValueError("correct must contain bools or 0/1")
        index = min(int(confidence * n_bins), n_bins - 1)
        # Multiplication may round either side of an edge to an integer.
        # Compare against the same boundaries returned to the caller.
        if confidence < bins[index]['lo']:
            index -= 1
        elif index < n_bins - 1 and confidence >= bins[index]['hi']:
            index += 1
        bins[index]['count'] += 1
        confidence_sums[index] += confidence
        correct_sums[index] += outcome
    for index, bin_ in enumerate(bins):
        if bin_['count']:
            bin_['mean_confidence'] = confidence_sums[index] / bin_['count']
            bin_['accuracy'] = correct_sums[index] / bin_['count']
    return bins


def expected_calibration_error(confidences, correct, n_bins=10):
    """Return count-weighted absolute calibration gaps, using reliability_bins."""
    bins = reliability_bins(confidences, correct, n_bins)
    total = len(confidences)
    return sum((bin_['count'] / total) * abs(bin_['accuracy'] - bin_['mean_confidence'])
               for bin_ in bins if bin_['count'])

"""Stdlib agreement metrics; unwired by design until G-01.5.

Labels must be hashable. Each function makes one pass over the paired input
sequences, retaining counts rather than observations: O(k**2) memory for k
labels. Results describe the supplied labels, not who produced or judged them.
"""

from collections import Counter


def confusion_matrix(a, b, labels=None):
    """Return (label_order, counts), with rows from a and columns from b.

    Default order is first appearance while visiting each (a[i], b[i]) pair.
    Explicit labels retain their order, must be unique and cover all observed
    labels, and may include unused labels. Empty or unequal inputs and invalid
    explicit label sets raise ValueError. Inputs are never modified.
    """
    if len(a) != len(b) or len(a) == 0:
        raise ValueError('inputs must be nonempty and equal length')
    order = [] if labels is None else list(labels)
    indices = {label: i for i, label in enumerate(order)}
    if len(indices) != len(order):
        raise ValueError('labels must be unique')
    counts = Counter()
    for left, right in zip(a, b):
        for label in (left, right):
            if label not in indices:
                if labels is not None:
                    raise ValueError('labels must cover all observations')
                indices[label] = len(order)
                order.append(label)
        counts[indices[left], indices[right]] += 1
    return order, [[counts[i, j] for j in range(len(order))]
                   for i in range(len(order))]


def cohens_kappa(a, b):
    """Return unweighted Cohen's kappa for nonempty, equal-length sequences.

    When expected agreement is 1 (both raters use the same single label),
    return 1.0 by convention rather than the undefined 0/0. Integer count
    arithmetic avoids cancellation when expected agreement is nearly 1.
    """
    _, matrix = confusion_matrix(a, b)
    rows = [sum(row) for row in matrix]
    columns = [sum(column) for column in zip(*matrix)]
    n = len(a)
    expected = sum(row * column for row, column in zip(rows, columns))
    observed = sum(matrix[i][i] for i in range(len(matrix)))
    denominator = n * n - expected
    return (n * observed - expected) / denominator if denominator else 1.0


def per_class_f1(gold, pred):
    """Return {label: {'precision': p, 'recall': r, 'f1': f}}.

    Include every label in gold or pred in the confusion matrix's first-seen
    order. A zero denominator yields 0.0 for that score. Empty or unequal
    sequences raise ValueError.
    """
    labels, matrix = confusion_matrix(gold, pred)
    columns = [sum(column) for column in zip(*matrix)]
    result = {}
    for i, label in enumerate(labels):
        true_positive = matrix[i][i]
        actual = sum(matrix[i])
        predicted = columns[i]
        result[label] = {
            'precision': true_positive / predicted if predicted else 0.0,
            'recall': true_positive / actual if actual else 0.0,
            'f1': 2 * true_positive / (actual + predicted)
            if actual + predicted else 0.0,
        }
    return result

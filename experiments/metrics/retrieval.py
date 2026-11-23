"""MT-03 retrieval metrics; unwired by design until G-03 / EX-04.

Callers must supply queries and neighbours from a single granularity level
(invariant I2); IDs and move labels alone cannot establish that boundary.
"""


def recall_at_k(ranked, relevant, k):
    """Fraction of all relevant IDs found in the first k ranked positions.

    Repeated IDs count once; short rankings still divide by len(relevant).
    Empty relevant sets and k < 1 raise ValueError.
    """
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant:
        raise ValueError("recall requires relevant IDs")
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mean_recall_at_k(queries, k):
    """Macro-average (ranked, relevant) queries, skipping empty relevant sets.

    Return recall_at_k, n (included queries), and skipped. Consume queries
    once with O(1) state beyond one query and its O(k) prefix workspace.
    Raise ValueError for k < 1 or no queries with nonempty relevant sets.
    """
    if k < 1:
        raise ValueError("k must be positive")
    total = 0.0
    n = skipped = 0
    for ranked, relevant in queries:
        if not relevant:
            skipped += 1
            continue
        total += recall_at_k(ranked, relevant, k)
        n += 1
    if not n:
        raise ValueError("mean recall requires queries with relevant IDs")
    return {'recall_at_k': total / n, 'n': n, 'skipped': skipped}


def same_move_rate(neighbours, query_move, k):
    """Matching move labels / available neighbours in the first k positions.

    neighbours is a sequence of move labels. Short sequences divide by their
    actual length, not k. Empty retrievals return 0.0; k < 1 raises ValueError.
    """
    if k < 1:
        raise ValueError("k must be positive")
    prefix = neighbours[:k]
    if not prefix:
        return 0.0
    return sum(move == query_move for move in prefix) / len(prefix)


def mean_same_move_rate(queries, k):
    """Macro-average (query_move, neighbour_moves) pairs; return rate and n.

    Empty neighbour sequences contribute zero and count in n. Consume queries
    once with O(1) state beyond one query and its O(k) prefix workspace.
    Raise ValueError for k < 1 or an empty query population.
    """
    if k < 1:
        raise ValueError("k must be positive")
    total = 0.0
    n = 0
    for query_move, neighbours in queries:
        total += same_move_rate(neighbours, query_move, k)
        n += 1
    if not n:
        raise ValueError("mean same-move rate requires queries")
    return {'rate': total / n, 'n': n}

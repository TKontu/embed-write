"""MT-05 layer disagreement; unwired by design until G-04.2.

The intended production caller is the G-04 fast/slow comparison gate.
"""


def layer_disagreement(pairs):
    """Summarize (fast_label, slow_label) pairs using slow as reference.

    Labels are hashable move labels. A disagreement means unequal labels;
    the slow reference is not an expert judgment or a correctness claim.
    Consume the iterable once with O(number of reference moves) memory.
    Raise ValueError for empty input. Rates are fractions, without intervals.
    """
    n = disagreements = 0
    per_move = {}
    for fast_label, slow_label in pairs:
        differs = int(fast_label != slow_label)
        n += 1
        disagreements += differs
        if slow_label not in per_move:
            per_move[slow_label] = {'n': 0, 'disagreements': 0}
        move = per_move[slow_label]
        move['n'] += 1
        move['disagreements'] += differs
    if not n:
        raise ValueError('pairs must not be empty')
    for move in per_move.values():
        move['rate'] = move['disagreements'] / move['n']
    return {'rate': disagreements / n, 'n': n,
            'disagreements': disagreements, 'per_move': per_move}

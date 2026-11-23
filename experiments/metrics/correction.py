"""MT-06 correction rates; unwired by design until todo-07 AD-10 / G-10.

The intended production caller is the edit-log consumer in todo-07.
"""


def correction_rate(entries):
    """Return overall, per-draft and per-move correction fractions and counts.

    Entries are mappings with hashable draft/move identifiers and string
    candidate/final values; extra keys are ignored. Corrected means exactly
    final != candidate: no whitespace, case or Unicode normalization.
    An unchanged acceptance counts as not corrected. Each entry has equal
    weight, including repeated entries in a draft or move.

    Consume the iterable once, keeping only O(drafts + moves) counters and
    the current entry, never the population. Raise ValueError for an empty
    population or any missing required key. No private data is read here.
    """
    n = corrected = 0
    per_draft, per_move = {}, {}
    for entry in entries:
        try:
            draft, move = entry['draft'], entry['move']
            differs = int(entry['final'] != entry['candidate'])
        except KeyError as exc:
            raise ValueError(f'missing required key: {exc.args[0]}') from exc
        n += 1
        corrected += differs
        for groups, key in ((per_draft, draft), (per_move, move)):
            counts = groups.setdefault(key, {'rate': 0, 'n': 0})
            counts['rate'] += differs
            counts['n'] += 1
    if not n:
        raise ValueError('entries must not be empty')
    for groups in (per_draft, per_move):
        for counts in groups.values():
            counts['rate'] /= counts['n']
    return {'rate': corrected / n, 'n': n,
            'per_draft': per_draft, 'per_move': per_move}

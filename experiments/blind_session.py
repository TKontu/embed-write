"""Blind-pair session design (BJ-02): interleaved pairs plus repeated pairs.

build_session is the production caller of blind_pair.make_pair and
record_session_choice of blind_pair.record_choice. The session is unwired until
a G-02 session is actually run (BJ-03, [H]); no judgment happens here.

Session files hold server-side state (opaque keys, arm mappings, repeat links)
and belong in private storage; only blind_pair.render_html(item.presentation)
goes to the browser, and it carries no item_id, repeat flag or arm name.
Sessions are small and held in memory; record parsing streams.
"""

import json
import math
from dataclasses import dataclass

from experiments import blind_pair


@dataclass(frozen=True)
class SessionItem:
    """One presented pair. repeat_of is the original item_id, or None."""

    item_id: str
    comparison: str
    presentation: blind_pair.Presentation
    repeat_of: object = None


def _interleave(queues, rng):
    """Greedy: take from the largest remaining comparison unlike the previous one."""
    order, previous = [], None
    remaining = {name: list(items) for name, items in queues.items() if items}
    while remaining:
        names = sorted(remaining)
        choices = [n for n in names if n != previous] or names
        best = max(len(remaining[n]) for n in choices)
        tied = [n for n in choices if len(remaining[n]) == best]
        name = tied[rng.randrange(len(tied))]
        order.append((name, remaining[name].pop()))
        if not remaining[name]:
            del remaining[name]
        previous = name
    return order


def build_session(comparisons, *, repeat_fraction, min_gap, rng):
    """Return an ordered list of SessionItem.

    comparisons maps a name to a list of (pair_id, text_x, arm_x, text_y, arm_y).
    Every pair appears once, interleaved so consecutive items differ in
    comparison when feasible; ceil(repeat_fraction * total) pairs are repeated
    at least min_gap items after their original, with left/right re-randomised
    by a fresh make_pair call. Raises ValueError if repeats cannot be placed.
    """
    if not 0 <= repeat_fraction <= 1:
        raise ValueError('repeat_fraction must be within [0, 1]')
    if min_gap < 1:
        raise ValueError('min_gap must be at least 1')
    queues = {}
    for name in sorted(comparisons):
        pairs = list(comparisons[name])
        rng.shuffle(pairs)
        queues[name] = pairs
    base = _interleave(queues, rng)
    total = len(base)
    n_repeats = math.ceil(repeat_fraction * total)
    seen = [pair[0] for _, pair in base]
    if len(set(seen)) != total:
        raise ValueError('pair_id values must be unique across the session')
    feasible = [i for i in range(total) if i + min_gap <= total]
    if n_repeats > len(feasible):
        raise ValueError(f'Cannot place {n_repeats} repeats with min_gap={min_gap} '
                         f'in {total} pairs')
    chosen = rng.sample(feasible, n_repeats)

    # Entries: (comparison, pair, original_slot or None); slot = index into base.
    entries = [(name, pair, None) for name, pair in base]
    for slot in chosen:
        origin = next(i for i, e in enumerate(entries) if e[2] is None and e[1] is base[slot][1])
        name = base[slot][0]
        positions = list(range(origin + min_gap, len(entries) + 1))
        clean = [p for p in positions
                 if (p == 0 or entries[p - 1][0] != name)
                 and (p == len(entries) or entries[p][0] != name)]
        options = clean or positions
        entries.insert(options[rng.randrange(len(options))], (name, base[slot][1], slot))

    ids = {}
    width = len(str(len(entries)))
    session = []
    for index, (name, pair, slot) in enumerate(entries):
        item_id = f'item-{index:0{width}d}'
        if slot is None:
            ids[id(pair)] = item_id
        session.append((item_id, name, pair, slot))
    result = []
    for item_id, name, pair, slot in session:
        repeat_of = None if slot is None else ids[id(pair)]
        result.append(SessionItem(item_id, name, blind_pair.make_pair(*pair, rng), repeat_of))
    return result


def _item_to_dict(item):
    p = item.presentation
    return dict(item_id=item.item_id, comparison=item.comparison, repeat_of=item.repeat_of,
                pair_id=p.pair_id, left=p.left, right=p.right, key=p.key,
                left_arm=p._left_arm, right_arm=p._right_arm)


def save_session(path, session):
    """Write server-side session state (keys, arms, repeat links) as JSON."""
    with open(path, 'w', encoding='utf-8') as output:
        json.dump([_item_to_dict(item) for item in session], output, ensure_ascii=False)


def load_session(path):
    with open(path, encoding='utf-8') as source:
        data = json.load(source)
    return [SessionItem(d['item_id'], d['comparison'],
                        blind_pair.Presentation(d['pair_id'], d['left'], d['right'], d['key'],
                                                d['left_arm'], d['right_arm']),
                        d['repeat_of'])
            for d in data]


def record_session_choice(path, session, item_id, choice, reason=None):
    """Record a choice for item_id with item_id, comparison and repeat_of added."""
    item = next((i for i in session if i.item_id == item_id), None)
    if item is None:
        raise KeyError(item_id)
    blind_pair.record_choice(path, item.presentation, choice, reason,
                             extra=dict(item_id=item.item_id, comparison=item.comparison,
                                        repeat_of=item.repeat_of))


def consistency_pairs(records):
    """Yield (pair_id, first_winner, repeat_winner) per repeated pair, streaming.

    Accepts JSON lines or decoded records in any order; only winners of items
    still awaiting their partner are buffered.
    """
    originals, pending = {}, {}
    for record in records:
        if isinstance(record, (str, bytes, bytearray)):
            if not record.strip():
                continue
            record = json.loads(record)
        repeat_of = record.get('repeat_of')
        if repeat_of is None:
            item_id = record['item_id']
            if item_id in pending:
                yield record['pair_id'], record['winner'], pending.pop(item_id)
            else:
                originals[item_id] = record['winner']
        elif repeat_of in originals:
            yield record['pair_id'], originals.pop(repeat_of), record['winner']
        else:
            pending[repeat_of] = record['winner']

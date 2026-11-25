"""Acceptance statistics over the local edit log (UX-05, library + CLI half).

Counts accept / edit / reject actions overall and per genre, streaming
``EditLogStore.iter_entries()`` once; memory is bounded by the number of
distinct genres. Each action is shown as a raw count and its share of the
total; there is no combined figure (invariant I8). Local only (I9).

Unwired by design: the app shell shows this to the expert in todo-06.

    python3 -m editlog.stats DB_PATH
"""

import argparse
import os
import sys
from dataclasses import dataclass

from editlog.store import EditLogStore

_ACTIONS = ('accept', 'edit', 'reject')


@dataclass(frozen=True)
class GenreStats:
    genre: str
    total: int
    accept: int
    edit: int
    reject: int


@dataclass(frozen=True)
class AcceptanceStats:
    total: int
    accept: int
    edit: int
    reject: int
    by_genre: tuple


def acceptance_stats(store):
    """Return AcceptanceStats for every entry in ``store`` (one pass)."""
    overall = dict.fromkeys(_ACTIONS, 0)
    genres = {}
    for _, entry in store.iter_entries():
        g = genres.setdefault(entry.genre, dict.fromkeys(_ACTIONS, 0))
        g[entry.action] += 1
        overall[entry.action] += 1
    by_genre = tuple(
        GenreStats(name, sum(c.values()), c['accept'], c['edit'], c['reject'])
        for name, c in sorted(genres.items()))
    return AcceptanceStats(sum(overall.values()), overall['accept'],
                           overall['edit'], overall['reject'], by_genre)


def _line(label, s):
    def part(action):
        n = getattr(s, action)
        share = 'n/a' if s.total == 0 else '%.1f%%' % (100.0 * n / s.total)
        return '%s %d (%s)' % (action, n, share)
    return '%s: total %d, %s' % (label, s.total,
                                 ', '.join(part(a) for a in _ACTIONS))


def format_stats(stats):
    """Plain-text lines: overall, then one line per genre."""
    lines = [_line('all', stats)]
    lines.extend(_line('genre %s' % g.genre, g) for g in stats.by_genre)
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python3 -m editlog.stats',
        description='Show accept/edit/reject counts from the local edit log.')
    parser.add_argument('db_path')
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db_path):
        print('error: no edit log at %s' % args.db_path, file=sys.stderr)
        return 2
    with EditLogStore(args.db_path) as store:
        print(format_stats(acceptance_stats(store)))
    return 0


if __name__ == '__main__':
    sys.exit(main())

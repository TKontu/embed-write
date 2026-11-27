"""Genre-file scaffold for the expert's seed list (todo-09 CO-13, feeds MV-01).

    python -m service.genre_scaffold new OUT.json --name NAME [--moves N]
        [--section-types a,b] [--force]
    python -m service.genre_scaffold check PATH

``new`` writes a genre file that passes ``service.genre.validate_genre`` with
N (default 3) placeholder moves. Every field the expert must write holds a
"TODO-" marker; no move content is invented (choosing moves is MV-01 [H]).
Legend colours are a fixed neutral palette the expert may change. Output is
deterministic: same arguments give byte-identical files.

``check`` loads and validates a file, then exits 1 listing every field that
still holds a scaffold marker ("TODO-move-" or "TODO-section-") (exit 0 when none remain, 2 when invalid).
Comment keys ("_"-prefixed) are skipped.

Production caller: the expert (MV-01) via this CLI. Pure stdlib.
"""

import argparse
import json
import os
import re
import sys

from service.genre import MAX_MOVES, GenreFileError, load_genre, validate_genre

MARK = 'TODO'
_MARKER = re.compile(rf'{MARK}-(move|section)-')
_PALETTE = ('#4f7cac', '#c0504d', '#4f9d69', '#d08b2c', '#8064a2',
            '#4bacc6', '#9b6a3c', '#c9539b', '#6b8e23', '#5a6b7c')
_OTHER = '#9a9a9a'
_COMMENT = (
    'Scaffold written by service.genre_scaffold; it holds no move content. '
    'Replace every "TODO-move-" / "TODO-section-" placeholder with your own: each move needs an id '
    '(short, unique, not "other"), a name, a one-sentence definition, at least two '
    'positive_examples and one near_miss. Rename legend.colors keys to match the '
    'move ids. Add or remove moves (1-10). Run "python -m service.genre_scaffold '
    'check FILE" until it exits 0. Bump "version" on any later content change.')


def scaffold(name, moves=3, section_types=()):
    """Return the scaffold genre object (validated)."""
    if not 1 <= moves <= MAX_MOVES:
        raise GenreFileError(f'moves: must be between 1 and {MAX_MOVES}')
    mv = []
    for i in range(1, moves + 1):
        p = f'{MARK}-move-{i}'
        mv.append({
            'id': p,
            'name': f'{p}-name',
            'definition': f'{p}-definition: one sentence in your words.',
            'positive_examples': [f'{p}-example-1', f'{p}-example-2'],
            'near_miss': f'{p}-near-miss',
        })
    obj = {
        '_comment': _COMMENT,
        'genre': name,
        'version': 1,
        'moves': mv,
        'legend': {
            'colors': {m['id']: _PALETTE[i] for i, m in enumerate(mv)},
            'other': _OTHER,
        },
    }
    if section_types:
        obj['section_types'] = [
            {'id': t, 'name': f'{MARK}-section-{t}-name',
             'headings': [f'{MARK}-section-{t}-heading']}
            for t in section_types]
    return validate_genre(obj)


def placeholders(value, path=''):
    """Paths of non-comment fields (keys or values) still holding a scaffold marker."""
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k.startswith('_'):
                continue
            sub = f'{path}.{k}' if path else k
            if _MARKER.search(k):
                found.append(f'{sub} (key)')
            found.extend(placeholders(v, sub))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(placeholders(v, f'{path}[{i}]'))
    elif isinstance(value, str) and _MARKER.search(value):
        found.append(path)
    return found


def dumps(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + '\n'


def _cmd_new(a):
    if os.path.exists(a.out) and not a.force:
        print(f'error: {a.out} exists; pass --force to overwrite', file=sys.stderr)
        return 2
    types = [t.strip() for t in a.section_types.split(',') if t.strip()] if a.section_types else []
    try:
        obj = scaffold(a.name, a.moves, types)
    except GenreFileError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    parent = os.path.dirname(a.out)
    if parent and not os.path.isdir(parent):
        print(f'error: parent directory not found: {parent}', file=sys.stderr)
        return 2
    with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(dumps(obj))
    print(f'wrote {a.out}: {a.moves} placeholder moves; fill the TODO fields, then run check')
    return 0


def _cmd_check(a):
    try:
        obj = load_genre(a.path)
    except GenreFileError as exc:
        print(f'invalid: {exc}', file=sys.stderr)
        return 2
    left = placeholders(obj)
    if left:
        print(f'{len(left)} placeholder field(s) remain:')
        for p in left:
            print(f'  {p}')
        return 1
    print(f'ok: {a.path} is valid with no placeholders')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m service.genre_scaffold')
    sub = ap.add_subparsers(dest='cmd', required=True)
    n = sub.add_parser('new', help='write a placeholder genre file')
    n.add_argument('out')
    n.add_argument('--name', required=True)
    n.add_argument('--moves', type=int, default=3)
    n.add_argument('--section-types', default='')
    n.add_argument('--force', action='store_true')
    c = sub.add_parser('check', help='validate and list remaining placeholders')
    c.add_argument('path')
    a = ap.parse_args(argv)
    return _cmd_new(a) if a.cmd == 'new' else _cmd_check(a)


if __name__ == '__main__':
    sys.exit(main())

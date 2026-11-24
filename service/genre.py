"""Versioned genre file: move inventory, definitions and legend (todo-09 MV-05).

Invariant I3: the legend is fixed per genre and stored with the pattern model;
it is never computed. This module loads and validates that stored file. Pure
stdlib.

Schema (JSON object; provisional until MV-03/MV-04 [H] fix the content):

    {
      "genre":   non-empty string,
      "version": integer >= 1 (bool rejected); bump on any content change,
      "moves":   list of 1..10 objects, each:
          "id":                non-empty string, unique, not "other"
          "name":              non-empty string
          "definition":        non-empty string (one sentence)
          "positive_examples": list of >= 2 non-empty strings
          "near_miss":         non-empty string
      "legend": {
          "colors": object mapping every move id (and only those) -> "#rrggbb"
          "other":  "#rrggbb", the neutral colour for the `other` class
      }
    }

Keys starting with "_" (e.g. "_note") are comments: ignored by validation and
excluded from the content hash, like "version".

Content hash: SHA-256 of sorted-key, compact JSON of the file minus "version"
and comment keys. Move order is content (it is the display order).

Dependent labels carry ``version_key(genre)`` = {"genre_version", "genre_hash"};
``labels_valid_for`` rejects them once either differs.

Unwired by design: production callers are LG-02 (legend rendering from the
genre file) and AN-01 / G-01.4 label exports (carry the version key).
"""

import hashlib
import json
import re

MAX_MOVES = 10
OTHER = 'other'
_HEX = re.compile(r'#[0-9a-fA-F]{6}\Z')
_MOVE_FIELDS = ('id', 'name', 'definition', 'positive_examples', 'near_miss')


class GenreFileError(ValueError):
    """Raised for an invalid genre file; the message names the field."""


def _fail(field, why):
    raise GenreFileError(f'{field}: {why}')


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        _fail(field, 'must be a non-empty string')


def _hex(value, field):
    if not isinstance(value, str) or not _HEX.match(value):
        _fail(field, 'must be a colour hex "#rrggbb"')


def validate_genre(obj):
    """Validate a parsed genre file; return it unchanged or raise GenreFileError."""
    if not isinstance(obj, dict):
        _fail('<root>', 'must be a JSON object')
    for key in ('genre', 'version', 'moves', 'legend'):
        if key not in obj:
            _fail(key, 'required field missing')
    _text(obj['genre'], 'genre')
    v = obj['version']
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        _fail('version', 'must be an integer >= 1')

    moves = obj['moves']
    if not isinstance(moves, list) or not moves:
        _fail('moves', 'must be a non-empty list')
    if len(moves) > MAX_MOVES:
        _fail('moves', f'{len(moves)} moves exceeds the maximum of {MAX_MOVES}')
    ids = []
    for i, m in enumerate(moves):
        where = f'moves[{i}]'
        if not isinstance(m, dict):
            _fail(where, 'must be an object')
        for key in _MOVE_FIELDS:
            if key not in m:
                _fail(f'{where}.{key}', 'required field missing')
        for key in ('id', 'name', 'definition', 'near_miss'):
            _text(m[key], f'{where}.{key}')
        if m['id'] == OTHER:
            _fail(f'{where}.id', f'"{OTHER}" is reserved for the neutral class')
        if m['id'] in ids:
            _fail(f'{where}.id', f'duplicate move id "{m["id"]}"')
        ids.append(m['id'])
        ex = m['positive_examples']
        if not isinstance(ex, list) or len(ex) < 2:
            _fail(f'{where}.positive_examples', 'must list at least two examples')
        for j, e in enumerate(ex):
            _text(e, f'{where}.positive_examples[{j}]')

    legend = obj['legend']
    if not isinstance(legend, dict):
        _fail('legend', 'must be an object')
    for key in ('colors', 'other'):
        if key not in legend:
            _fail(f'legend.{key}', 'required field missing')
    colors = legend['colors']
    if not isinstance(colors, dict):
        _fail('legend.colors', 'must be an object')
    for mid in colors:
        if mid not in ids:
            _fail(f'legend.colors.{mid}', 'legend entry for unknown move')
    for mid in ids:
        if mid not in colors:
            _fail(f'legend.colors.{mid}', 'move missing from legend')
        _hex(colors[mid], f'legend.colors.{mid}')
    _hex(legend['other'], 'legend.other')
    return obj


def load_genre(path):
    """Read, parse and validate a genre file."""
    try:
        with open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
    except (OSError, ValueError) as exc:
        raise GenreFileError(f'<file> {path}: {exc}') from exc
    return validate_genre(obj)


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if not k.startswith('_')}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def content_hash(obj):
    """SHA-256 hex of the canonical content (excludes version and _comments)."""
    content = {k: v for k, v in _strip(obj).items() if k != 'version'}
    blob = json.dumps(content, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def check_version_bump(old, new):
    """Raise GenreFileError unless a content change came with a higher version."""
    if new['version'] < old['version']:
        _fail('version', f'decreased from {old["version"]} to {new["version"]}')
    if content_hash(old) != content_hash(new) and new['version'] == old['version']:
        _fail('version', f'content changed but version stayed {new["version"]}')


def version_key(obj):
    """Key that dependent label records carry."""
    return {'genre_version': obj['version'], 'genre_hash': content_hash(obj)}


def labels_valid_for(obj, label_record):
    """True only if the record was produced under this exact genre content+version."""
    key = version_key(obj)
    return all(label_record.get(k) == v for k, v in key.items())

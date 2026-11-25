"""Append-only, versioned store of expert sentence labels (todo-09 AN-07).

Pure stdlib, offline (I9). One JSON object per line (JSONL). Every stored
record carries the genre name and ``genre.version_key(genre)``
({"genre_version", "genre_hash"}), so labels made under one move inventory are
never silently read under another:

* ``read(genre)`` returns only records whose key matches ``genre`` exactly
  (``labels_valid_for`` semantics); ``include_stale=True`` adds same-genre
  records from other inventory versions, each marked ``"stale": True``
  (current ones carry ``"stale": False``). Records of a different genre name
  are neither returned nor counted.
* Later appends for the same sentence_id supersede earlier ones within the
  same version key (last write wins); the file keeps the full history
  (``history(sentence_id)``).

Durability: each append is one ``write`` of one newline-terminated line on an
O_APPEND handle, then flush + fsync. A final line without its newline (a torn
write) or an unparsable line raises ``TruncatedRecordError`` /
``AnnotationStoreError`` naming the line; opening the store never reads the
file, and append refuses to write after a torn tail.

Memory: reads stream line by line; the supersede index holds one record per
(sentence_id, version key) seen.

Unwired by design: AN-01 (annotation tool) appends; G-01.4 reads.
"""

import json
import os

from service.genre import labels_valid_for, version_key

REQUIRED = ('sentence_id', 'label', 'annotator', 'timestamp')
RESERVED = ('genre', 'genre_version', 'genre_hash', 'stale')
OTHER = 'other'


class AnnotationStoreError(ValueError):
    """Invalid record or unreadable store."""


class TruncatedRecordError(AnnotationStoreError):
    """The store ends in a partial (torn) line."""


class AnnotationStore:
    def __init__(self, path):
        self.path = path

    # -- writing -------------------------------------------------------
    def append(self, genre_obj, record):
        """Validate ``record`` against ``genre_obj`` and append it durably."""
        out = _validated(genre_obj, record)
        line = json.dumps(out, sort_keys=True, ensure_ascii=False) + '\n'
        self._check_tail()
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return dict(out)

    def _check_tail(self):
        try:
            with open(self.path, 'rb') as fh:
                fh.seek(0, os.SEEK_END)
                if fh.tell() == 0:
                    return
                fh.seek(-1, os.SEEK_END)
                last = fh.read(1)
        except FileNotFoundError:
            return
        if last != b'\n':
            raise TruncatedRecordError(
                f'{self.path}: last line is incomplete (torn write); '
                'repair the store before appending')

    # -- reading -------------------------------------------------------
    def _records(self):
        """Yield (line_no, record) streaming; raise on corrupt/torn lines."""
        try:
            fh = open(self.path, encoding='utf-8')
        except FileNotFoundError:
            return
        with fh:
            for no, line in enumerate(fh, 1):
                if not line.endswith('\n'):
                    raise TruncatedRecordError(
                        f'{self.path}: line {no} is incomplete (torn write)')
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AnnotationStoreError(
                        f'{self.path}: line {no} is not valid JSON: {exc}') from None
                if not isinstance(obj, dict):
                    raise AnnotationStoreError(
                        f'{self.path}: line {no} is not a JSON object')
                yield no, obj

    def read(self, genre_obj, *, include_stale=False):
        """Latest label per sentence (first-seen order) under ``genre_obj``'s exact version key.

        With ``include_stale`` also the latest per sentence of each other
        version of the same genre, marked ``stale: True``.
        """
        name = genre_obj['genre']
        latest = {}  # (sentence_id, genre_version, genre_hash) -> record
        for _, obj in self._records():
            if obj.get('genre') != name:
                continue
            current = labels_valid_for(genre_obj, obj)
            if not current and not include_stale:
                continue
            key = (obj.get('sentence_id'), obj.get('genre_version'),
                   obj.get('genre_hash'))
            latest[key] = dict(obj, stale=not current)
        return list(latest.values())

    def stale_count(self, genre_obj):
        """Number of stored records of this genre under another version key."""
        name = genre_obj['genre']
        return sum(1 for _, obj in self._records()
                   if obj.get('genre') == name
                   and not labels_valid_for(genre_obj, obj))

    def history(self, sentence_id):
        """All stored records for ``sentence_id`` in write order (any version)."""
        return [obj for _, obj in self._records()
                if obj.get('sentence_id') == sentence_id]


def _validated(genre_obj, record):
    if not isinstance(record, dict):
        raise AnnotationStoreError('record must be an object')
    for k in RESERVED:
        if k in record:
            raise AnnotationStoreError(f'{k!r} is set by the store, not the caller')
    for k in REQUIRED:
        v = record.get(k)
        if not isinstance(v, str) or not v.strip():
            raise AnnotationStoreError(f'{k!r} must be a non-empty string')
    allowed = {m['id'] for m in genre_obj['moves']} | {OTHER}
    if record['label'] not in allowed:
        raise AnnotationStoreError(
            f'label {record["label"]!r} is not a move of genre '
            f'{genre_obj["genre"]!r} v{genre_obj["version"]} nor {OTHER!r}')
    out = dict(record)
    out['genre'] = genre_obj['genre']
    out.update(version_key(genre_obj))
    return out

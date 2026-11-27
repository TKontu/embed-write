"""G-02.3 exemplar pool: sections of TRAINING-split reports for ``g02_generate --pool``.

``iter_pool(documents, split, genre, min_words=40, max_per_type=None)`` takes an iterable of
``(doc_id, markdown)`` and yields ``{section_id, report_id, section_type, text}`` records, one
document at a time, with the same section ids (``<doc_id>#s<index>``), section reader
(``annotation_sample._sections``) and genre mapping as ``g02_notes.select_sections``.
Unmapped/``unknown`` sections and sections under ``min_words`` words are skipped;
``max_per_type`` keeps the first N per section type in corpus order. Every document must be in
``split.train_ids``: a test or unassigned id raises ``SplitLeakError`` (CLI exit 2, the partial
output is removed), so held-out reports never reach the pool.

Memory bound: one document's text plus a per-type counter; records are written as they are
produced, so the process never holds the corpus (memory O(one document); the output grows on
disk only). The CLI builds the split from the sorted list of ``*.md`` ids, O(document count) ids.

The output holds corpus text: written 0600, refused if it already exists. Keep it private.

Production caller: the CLI ``python -m experiments.g02_pool``, whose line ``g02_notes`` prints
(``pool:``) with the same split arguments; consumer: ``experiments.g02_generate --pool``.
Offline (I9): reads local files only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator

from experiments.annotation_sample import UNKNOWN, _heading_map
from experiments.corpus import iter_documents
from experiments.g02_notes import _doc_sections
from experiments.splits import DocumentSplit, SplitLeakError, split_documents
from service.genre import load_genre

_WORD = re.compile(r'\w+')


def iter_pool(documents: Iterable[tuple[str, str]], split: DocumentSplit, genre, *,
              min_words: int = 40, max_per_type: int | None = None) -> Iterator[dict]:
    headings = _heading_map(genre)
    counts: dict[str, int] = {}
    for doc_id, markdown in documents:
        if doc_id not in split.train_ids:
            kind = 'test' if doc_id in split.test_ids else 'unassigned'
            raise SplitLeakError(f'{kind} document in exemplar pool: {doc_id!r}')
        for ix, (st, text) in sorted(_doc_sections(markdown, headings).items()):
            if st == UNKNOWN or len(_WORD.findall(text)) < min_words:
                continue
            if max_per_type is not None and counts.get(st, 0) >= max_per_type:
                continue
            counts[st] = counts.get(st, 0) + 1
            yield {'section_id': f'{doc_id}#s{ix}', 'report_id': doc_id, 'section_type': st,
                   'text': text}


def _train_documents(root: Path, split: DocumentSplit) -> Iterator[tuple[str, str]]:
    for d in iter_documents(root):
        rel = d.path.relative_to(root).as_posix()
        if rel in split.train_ids:
            yield rel, d.text


def main(argv=None, *, genre=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m experiments.g02_pool')
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--genre', required=True)
    ap.add_argument('--split-seed', type=int, required=True)
    ap.add_argument('--test-fraction', type=float, required=True)
    ap.add_argument('--min-words', type=int, default=40)
    ap.add_argument('--max-per-type', type=int, default=None)
    ap.add_argument('--out', required=True, help='pool JSONL (private, 0600, never overwritten)')
    a = ap.parse_args(argv)
    if a.max_per_type is not None and a.max_per_type < 0:
        ap.error('--max-per-type must be >= 0')
    if os.path.exists(a.out):
        ap.error(f'--out {a.out} exists; refusing to overwrite')
    root = Path(a.corpus)
    if not root.is_dir():
        ap.error(f'corpus directory not found: {root}')
    if genre is None:
        genre = load_genre(a.genre)
    ids = sorted(q.relative_to(root).as_posix() for q in root.rglob('*.md') if q.is_file())
    split = split_documents(ids, a.test_fraction, a.split_seed)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    written, reports, types = 0, set(), {}
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            for rec in iter_pool(_train_documents(root, split), split, genre,
                                 min_words=a.min_words, max_per_type=a.max_per_type):
                fh.write(json.dumps(rec, sort_keys=True) + '\n')
                written += 1
                reports.add(rec['report_id'])
                types[rec['section_type']] = types.get(rec['section_type'], 0) + 1
    except SplitLeakError as e:
        os.unlink(a.out)
        print(f'error: split leak, nothing written: {e}', file=sys.stderr)
        return 2
    except BaseException:
        os.unlink(a.out)
        raise
    print(json.dumps({'written': written, 'reports': len(reports),
                      'section_types': dict(sorted(types.items()))}))
    return 0


if __name__ == '__main__':
    sys.exit(main())

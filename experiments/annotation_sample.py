"""AN-02 stratified annotation sample over held-out (test) documents.

``build_manifest`` streams ``(doc_id, markdown)`` pairs one at a time and never
holds the corpus: it retains one small candidate tuple per test-document
sentence, ``(doc_id, section_type, sentence_id, ordinal)``, i.e. O(number of
test sentences) ids, no text. Every document must be in the split's test set
(``SplitLeakError`` otherwise).

Headings are ATX (``#``..``######``, level = ``#`` count) or setext (a paragraph
underlined by ``===``, level 1, or ``---``, level 2); lines inside ``` or ~~~ code
fences (also inside blockquotes and list items) are never headings and are excluded
from the text, so fenced code (opener, body, closer) never yields a sentence. Heading text is
mapped through the genre's ``section_types`` aliases with ``normalize_heading``. Each sentence takes the type
of the nearest enclosing mapped heading: an unmapped heading deeper than the
current mapped one inherits its type, while any heading at the same or a higher
level closes it. Text before any heading, or under an unmapped heading with no
enclosing mapped heading, is ``unknown`` (counted).

Allocation over (report, section type) strata: if n >= number of non-empty
section types, each type first receives one seat in a seeded-random stratum of
that type; the remaining seats are split proportionally to remaining stratum
capacity by largest remainder (seeded tie-break). A seeded repeat subset of
``round(repeat_fraction * drawn)`` entries supports AN-04.

Sentence ids are ``<doc_id>:<sha256(sentence)[:16]>`` via ``sentence_keys``
(repeats in a document get ``#n``); the manifest carries no sentence text.

Production caller: the CLI, run on the private corpus before AN-03 (pending).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Iterable

from experiments.corpus import iter_documents
from experiments.splits import DocumentSplit, split_documents
from service.genre import load_genre, normalize_heading, version_key
from service.segment import segment_sentences
from service.sentence_keys import sentence_keys

SCHEMA_VERSION = 1
UNKNOWN = 'unknown'
MEMORY_BOUND = ('O(test sentences) candidate tuples (doc_id, section_type, sentence_id, '
                'ordinal); one document text at a time; no sentence text retained')
_HEADING = re.compile(r'^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$')
_SETEXT = re.compile(r'^ {0,3}(=+|-+)[ \t]*$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_QUOTE = re.compile(r'^ {0,3}> ?')
_LIST_MARK = re.compile(r'^ {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+')
_NOT_SETEXT_START = re.compile(r'^ {0,3}(?:[-*+]|\d+[.)])[ \t]|^ {0,3}>')


def _heading_map(genre):
    return {normalize_heading(h): t['id']
            for t in genre.get('section_types', []) for h in t['headings']}


def _unquote(line):
    """Return (blockquote depth, line with the ``>`` markers removed)."""
    depth = 0
    while (m := _QUOTE.match(line)):
        line, depth = line[m.end():], depth + 1
    return depth, line


def _fence_open(line, cols):
    """Match a fence opener inside optional containers -> (match, depth, col, cols).

    ``cols`` is the stack of open list items' content columns (outermost first). A
    non-blank line indented less than a column closes that item and its nested ones;
    list markers after the deepest kept column push new columns. ``col`` is the
    content column the line's text (and any fence) sits at, 0 outside lists. State
    stays O(nesting depth).
    """
    depth, rest = _unquote(line)
    if rest.strip():
        keep = 0
        while keep < len(cols) and rest[:cols[keep]] == ' ' * cols[keep]:
            keep += 1
        cols = cols[:keep]
    col = cols[-1] if cols else 0
    while (mark := _LIST_MARK.match(rest[col:])):
        col += mark.end()
        cols = cols + [col]
    return _FENCE.match(rest[col:]), depth, col, cols


def _fence_close(line, fence):
    """True when ``line`` closes ``fence`` (char, length, depth, col) at its container prefix."""
    char, length, depth, col = fence
    got, rest = _unquote(line)
    if got != depth or rest[:col] != ' ' * col:
        return False
    m = _FENCE.match(rest[col:])
    return bool(m and m.group(1)[0] == char and len(m.group(1)) >= length
                and not m.group(2).strip())


def _fence_left(line, fence):
    """True when ``line`` leaves the container of ``fence`` (a fence is never lazy).

    A blockquote fence ends at a line of lower quote depth (a blank line included); a
    list-item fence ends at a non-blank line not indented to its column. Top-level
    fences (depth 0, col 0) never end this way.
    """
    _, _, depth, col = fence
    got, rest = _unquote(line)
    if got < depth:
        return True
    return bool(col and rest.strip() and rest[:col] != ' ' * col)


def _sections(markdown, headings):
    """Yield (section_type, heading_text, section_index, paragraph) per blank-line paragraph."""
    current, heading, index, para = UNKNOWN, None, 0, []
    mapped = []  # stack of (level, section_type) for enclosing mapped headings
    fence = None  # (char, length, quote depth, list column) of the open code fence
    cols = []  # content columns of the open (nested) list items, outermost first
    fenced = False  # pending paragraph text includes a code fence
    lines = markdown.splitlines()
    start = 0
    if lines and lines[0] == '---':  # YAML front matter: skip through closing ---/...
        for i in range(1, len(lines)):
            if lines[i] in ('---', '...'):
                start = i + 1
                break
    for line in lines[start:]:
        if fence and _fence_left(line, fence):
            fence = None
            while para and not para[-1].strip():
                para.pop()
            if para:
                yield current, heading, index, '\n'.join(para)
            para, fenced = [], False
        if fence:  # fenced text is excluded from the paragraph
            if _fence_close(line, fence):
                fence = None
            continue
        m, depth, col, cols = _fence_open(line, cols)
        if m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)), depth, col)
            fenced = True
            continue
        promotable = para and not fenced and not _NOT_SETEXT_START.match(para[0])
        atx, setext = _HEADING.match(line), promotable and _SETEXT.match(line)
        if atx or setext or not line.strip():
            if setext:
                text, level = ' '.join(p.strip() for p in para), 1 if '=' in line else 2
                para = []
            elif atx:
                text, level = atx.group(2), len(atx.group(1))
            if para:
                yield current, heading, index, '\n'.join(para)
                para = []
            fenced = False
            if atx or setext:
                heading = text
                while mapped and mapped[-1][0] >= level:
                    mapped.pop()
                section = headings.get(normalize_heading(text))
                if section is not None:
                    mapped.append((level, section))
                current = mapped[-1][1] if mapped else UNKNOWN
                index += 1
        else:
            para.append(line)
    if para:
        yield current, heading, index, '\n'.join(para)


def document_sentences(doc_id, markdown, headings):
    """Sentences of one document in order, with the ids the manifest uses.

    Returns dicts {sentence_id, section_type, heading, section_index, ordinal, text};
    ``headings`` is ``heading_map(genre)``. Public for AN-01 (experiments/annotate.py).
    """
    typed = [(st, h, ix, s) for st, h, ix, text in _sections(markdown, headings)
             for s in segment_sentences(text)]
    hashes = [hashlib.sha256(s.encode('utf-8')).hexdigest()[:16] for *_, s in typed]
    keys = sentence_keys(doc_id, hashes) if typed else ()
    return [{'sentence_id': key, 'section_type': st, 'heading': h, 'section_index': ix,
             'ordinal': i, 'text': s}
            for i, ((st, h, ix, s), key) in enumerate(zip(typed, keys))]


def _candidates(doc_id, markdown, headings):
    return [(doc_id, r['section_type'], r['sentence_id'], r['ordinal'])
            for r in document_sentences(doc_id, markdown, headings)]


heading_map = _heading_map


def _allocate(sizes, n, rng):
    """sizes: {(doc, type): count} (sorted keys). Return {stratum: seats}."""
    strata = sorted(sizes)
    total = sum(sizes.values())
    if n >= total:
        return dict(sizes)
    seats = {s: 0 for s in strata}
    types = sorted({t for _, t in strata})
    if n >= len(types):
        for t in types:
            seats[rng.choice([s for s in strata if s[1] == t])] += 1
    left = n - sum(seats.values())
    cap = {s: sizes[s] - seats[s] for s in strata}
    room = sum(cap.values())
    if left and room:
        rem = []
        for s in strata:
            q, r = divmod(left * cap[s], room)
            seats[s] += q
            rem.append((-r, rng.random(), s))
        short = n - sum(seats.values())
        for _, _, s in sorted(rem)[:short]:
            seats[s] += 1
    return seats


def build_manifest(documents: Iterable[tuple[str, str]], split: DocumentSplit, genre,
                   n: int = 300, repeat_fraction: float = 0.1, seed: int = 0) -> dict:
    if n < 0 or not 0 <= repeat_fraction <= 1:
        raise ValueError('n must be >= 0 and repeat_fraction in [0, 1]')
    headings = _heading_map(genre)
    by_stratum: dict[tuple[str, str], list[tuple]] = {}
    seen = set()
    for doc_id, markdown in documents:
        split.check_eval([doc_id])
        if doc_id in seen:
            raise ValueError(f'duplicate document id {doc_id!r}')
        seen.add(doc_id)
        for cand in _candidates(doc_id, markdown, headings):
            by_stratum.setdefault((cand[0], cand[1]), []).append(cand)
    rng = random.Random(seed)
    sizes = {s: len(v) for s, v in by_stratum.items()}
    seats = _allocate(sizes, n, rng)
    chosen = []
    for s in sorted(by_stratum):
        chosen.extend(rng.sample(by_stratum[s], seats[s]))
    chosen.sort(key=lambda c: (c[0], c[3]))
    entries = [{'sentence_id': key, 'doc_id': d, 'section_type': st, 'ordinal': i}
               for d, st, key, i in chosen]
    ids = [e['sentence_id'] for e in entries]
    repeat = sorted(rng.sample(ids, round(repeat_fraction * len(ids))))
    label = lambda s: f'{s[0]}|{s[1]}'
    test_blob = '\n'.join(sorted(split.test_ids)).encode('utf-8')
    return {
        'schema_version': SCHEMA_VERSION,
        'seed': seed,
        'genre': version_key(genre),
        'split_test_ids_sha256': hashlib.sha256(test_blob).hexdigest(),
        'memory_bound': MEMORY_BOUND,
        'n_requested': n,
        'n_drawn': len(entries),
        'repeat_fraction': repeat_fraction,
        'unknown_sentences': sum(v for s, v in sizes.items() if s[1] == UNKNOWN),
        'candidates_per_stratum': {label(s): v for s, v in sorted(sizes.items())},
        'drawn_per_stratum': {label(s): seats[s] for s in sorted(seats) if seats[s]},
        'entries': entries,
        'repeat': repeat,
    }


def write_manifest(path, manifest) -> None:
    text = json.dumps(manifest, sort_keys=True, indent=2) + '\n'
    Path(path).write_text(text, encoding='utf-8')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--corpus', required=True)
    p.add_argument('--genre', required=True)
    p.add_argument('--split-seed', type=int, required=True)
    p.add_argument('--test-fraction', type=float, required=True)
    p.add_argument('--n', type=int, default=300)
    p.add_argument('--repeat-fraction', type=float, default=0.1)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--out', required=True)
    args = p.parse_args(argv)
    root = Path(args.corpus)
    if not root.is_dir():
        p.error(f'corpus directory not found: {root}')
    ids = sorted(q.relative_to(root).as_posix() for q in root.rglob('*.md') if q.is_file())
    split = split_documents(ids, args.test_fraction, args.split_seed)
    docs = ((d.path.relative_to(root).as_posix(), d.text) for d in iter_documents(root))
    test_docs = ((d, t) for d, t in docs if d in split.test_ids)
    manifest = build_manifest(test_docs, split, load_genre(args.genre), n=args.n,
                              repeat_fraction=args.repeat_fraction, seed=args.seed)
    write_manifest(args.out, manifest)
    print(f"wrote {args.out}: {manifest['n_drawn']} sentences, {len(manifest['repeat'])} repeat")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

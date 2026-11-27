"""G-02.2 neutral-notes runner: ~30 held-out sections reduced to facts, no phrasing.

``select_sections(documents, split, genre, n=30, seed=0, min_words=40)`` takes a zero-argument
callable returning a fresh ``(doc_id, markdown)`` iterator and streams it twice: pass one keeps
one small id tuple per candidate section (no text), pass two keeps the text of the chosen
sections only, so memory is O(candidate sections) ids plus the ~n selected texts. Every document
must be in the split's test set (``SplitLeakError`` otherwise). A section is the paragraphs
under one ATX heading (``annotation_sample._sections``); unmapped/``unknown`` sections and
sections under ``min_words`` words are skipped. Selection is seeded round-robin over section
types (stratified), preferring a report not yet used; a report is reused only once no unused
report has a candidate of that type.

``extract_notes(sections, model, out_path=...)`` asks an injected ``model(prompt) -> str`` for
bulleted facts and appends one record per section:
  {section_id, report_id, section_type, notes, model, prompt_version, prompt_hash}
the NotesRecord shape that ``experiments.g02_generate.iter_generate`` consumes (G-02.3).
Resumable: sections already in ``out_path`` under the same model id and ``PROMPT_VERSION``
are skipped.

``leak_review(sections, records, n=6, ...)`` is the mechanical half of the leaked-phrasing
check: it flags every note sharing a word n-gram with its source section and draws a seeded
expert sample. The verdict belongs to the expert (G-02.2 is [A→H]); this never decides it.

Stdout, only when every selected section has a notes record: a ``pool:`` line naming the
``experiments.g02_pool`` command (same corpus, genre, split and ``--min-words``; output
``g02_pool.jsonl`` next to ``--out``) and a ``next:`` line naming the ``g02_generate`` command with
that pool and the actual paths; always last, the JSON summary line.

``--sections-out PATH`` also writes the selected original sections as private JSONL
``{section_id, report_id, section_type, text}`` (mode 0600; refused if PATH exists), the
``--originals`` input of ``experiments.g02_session`` (G-02.4 C vs original). It holds corpus text:
keep it in private storage.

Production caller: the CLI ``python -m experiments.g02_notes`` for G-02.2, feeding G-02.3.
``prelabel.local_model`` posts only to a loopback endpoint (service.network_guard, I9).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shlex
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator

from experiments.annotation_sample import UNKNOWN, _heading_map, _sections
from experiments.corpus import iter_documents
from experiments.prelabel import local_model
from experiments.splits import DocumentSplit, split_documents
from service.genre import load_genre

PROMPT_VERSION = 'g02.2-v1'
_WORD = re.compile(r'\w+')

PROMPT = """Extract the content of the report section below as neutral notes.
Rules:
- facts only: quantities, names, findings, decisions, conditions;
- one short bullet per fact, each line starting with "- ";
- do not reuse the section's wording or sentence structure; no quotations;
- no introduction, no commentary.

SECTION TYPE: {section_type}
SECTION:
{text}
"""


def _doc_sections(markdown, headings):
    """{section_index: (section_type, text)} for one document."""
    out: dict[int, tuple[str, list[str]]] = {}
    for st, _heading, ix, para in _sections(markdown, headings):
        out.setdefault(ix, (st, []))[1].append(para)
    return {ix: (st, '\n\n'.join(paras)) for ix, (st, paras) in out.items()}


def select_sections(documents: Callable[[], Iterable[tuple[str, str]]], split: DocumentSplit,
                    genre, *, n: int = 30, seed: int = 0, min_words: int = 40) -> list[dict]:
    if n < 0:
        raise ValueError('n must be >= 0')
    headings = _heading_map(genre)
    by_type: dict[str, list[tuple[str, int]]] = {}
    seen = set()
    for doc_id, markdown in documents():
        split.check_eval([doc_id])
        if doc_id in seen:
            raise ValueError(f'duplicate document id {doc_id!r}')
        seen.add(doc_id)
        for ix, (st, text) in sorted(_doc_sections(markdown, headings).items()):
            if st != UNKNOWN and len(_WORD.findall(text)) >= min_words:
                by_type.setdefault(st, []).append((doc_id, ix))
    rng = random.Random(seed)
    pools = {t: rng.sample(c, len(c)) for t, c in sorted(by_type.items())}
    order = sorted(pools)
    rng.shuffle(order)
    chosen: list[tuple[str, int, str]] = []
    used_reports: set[str] = set()
    while len(chosen) < n and any(pools.values()):
        for t in order:
            if len(chosen) >= n or not pools[t]:
                continue
            pool = pools[t]
            pick = next((c for c in pool if c[0] not in used_reports), pool[0])
            pool.remove(pick)
            used_reports.add(pick[0])
            chosen.append((pick[0], pick[1], t))
    wanted: dict[str, set[int]] = {}
    for d, ix, _ in chosen:
        wanted.setdefault(d, set()).add(ix)
    texts = {}
    for doc_id, markdown in documents():
        if doc_id in wanted:
            split.check_eval([doc_id])
            secs = _doc_sections(markdown, headings)
            for ix in wanted[doc_id]:
                texts[(doc_id, ix)] = secs[ix][1]
    return [{'section_id': f'{d}#s{ix}', 'report_id': d, 'section_type': t,
             'text': texts[(d, ix)]} for d, ix, t in sorted(chosen)]


def build_prompt(section: dict) -> str:
    return PROMPT.format(section_type=section['section_type'], text=section['text'])


def _done(out_path, model_id) -> set:
    try:
        with open(out_path, encoding='utf-8') as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        return set()
    return {r['section_id'] for r in rows
            if r.get('model') == model_id and r.get('prompt_version') == PROMPT_VERSION}


def iter_notes(sections: Iterable[dict], model, *, out_path) -> Iterator[dict]:
    model_id = getattr(model, 'model_id', 'unknown')
    done = _done(out_path, model_id)
    with open(out_path, 'a', encoding='utf-8') as fh:
        for s in sections:
            if s['section_id'] in done:
                continue
            prompt = build_prompt(s)
            rec = {'section_id': s['section_id'], 'report_id': s['report_id'],
                   'section_type': s['section_type'], 'notes': model(prompt).strip(),
                   'model': model_id, 'prompt_version': PROMPT_VERSION,
                   'prompt_hash': hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]}
            fh.write(json.dumps(rec, sort_keys=True) + '\n')
            fh.flush()
            done.add(s['section_id'])
            yield rec


def extract_notes(sections, model, *, out_path) -> list[dict]:
    """Notes for every section not yet done; returns the records written by this call."""
    return list(iter_notes(sections, model, out_path=out_path))


def _ngrams(text, n) -> set:
    w = [t.lower() for t in _WORD.findall(text)]
    return {' '.join(w[i:i + n]) for i in range(len(w) - n + 1)}


def leak_review(sections: Iterable[dict], records: Iterable[dict], *, n: int = 6,
                sample_size: int = 10, seed: int = 0) -> dict:
    """Flag notes sharing any word n-gram with their source; seeded sample for the expert."""
    src = {s['section_id']: _ngrams(s['text'], n) for s in sections}
    recs = [r for r in records if r['section_id'] in src]
    flagged = []
    for r in recs:
        shared = sorted(_ngrams(r['notes'], n) & src[r['section_id']])
        if shared:
            flagged.append({'section_id': r['section_id'], 'shared_ngrams': shared})
    ids = sorted({r['section_id'] for r in recs})
    sample = sorted(random.Random(seed).sample(ids, min(sample_size, len(ids))))
    return {'ngram_n': n, 'n_records': len(recs), 'flagged': flagged,
            'expert_sample': sample, 'verdict': None,
            'note': 'mechanical check only; the leaked-phrasing verdict is the expert\'s (G-02.2 [A->H])'}


def _write_sections(path, sections) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        for s in sections:
            fh.write(json.dumps({k: s[k] for k in ('section_id', 'report_id', 'section_type',
                                                   'text')}, sort_keys=True) + '\n')


def main(argv=None, *, model=None, genre=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m experiments.g02_notes')
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--genre', required=True)
    ap.add_argument('--split-seed', type=int, required=True)
    ap.add_argument('--test-fraction', type=float, required=True)
    ap.add_argument('--n', type=int, default=30)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--min-words', type=int, default=40)
    ap.add_argument('--ngram', type=int, default=6)
    ap.add_argument('--sample-size', type=int, default=10)
    ap.add_argument('--model-url', help='loopback OpenAI-compatible endpoint (I9)')
    ap.add_argument('--model-name', default='local')
    ap.add_argument('--out', required=True, help='notes JSONL; review goes to <out>.review.json')
    ap.add_argument('--sections-out',
                    help='also write the selected original sections JSONL (private, G-02.4)')
    a = ap.parse_args(argv)
    if a.sections_out and os.path.exists(a.sections_out):
        ap.error(f'--sections-out {a.sections_out} exists; refusing to overwrite')
    if model is None:
        if not a.model_url:
            ap.error('--model-url is required unless a model is injected')
        model = local_model(a.model_url, model=a.model_name)
    root = Path(a.corpus)
    if not root.is_dir():
        ap.error(f'corpus directory not found: {root}')
    if genre is None:
        genre = load_genre(a.genre)
    ids = sorted(q.relative_to(root).as_posix() for q in root.rglob('*.md') if q.is_file())
    split = split_documents(ids, a.test_fraction, a.split_seed)

    def documents():
        for d in iter_documents(root):
            rel = d.path.relative_to(root).as_posix()
            if rel in split.test_ids:
                yield rel, d.text

    sections = select_sections(documents, split, genre, n=a.n, seed=a.seed, min_words=a.min_words)
    if a.sections_out:
        _write_sections(a.sections_out, sections)
    written = extract_notes(sections, model, out_path=a.out)
    model_id = getattr(model, 'model_id', 'unknown')
    with open(a.out, encoding='utf-8') as fh:
        records = [r for r in map(json.loads, filter(str.strip, fh))
                   if r.get('model') == model_id and r.get('prompt_version') == PROMPT_VERSION]
    review = leak_review(sections, records, n=a.ngram, sample_size=a.sample_size, seed=a.seed)
    Path(a.out + '.review.json').write_text(json.dumps(review, sort_keys=True, indent=2) + '\n',
                                            encoding='utf-8')
    complete = review['n_records'] == len(sections)
    if complete:
        pool_out = os.path.join(os.path.dirname(a.out), 'g02_pool.jsonl')
        print('pool: ' + shlex.join([
            'python', '-m', 'experiments.g02_pool', '--corpus', a.corpus, '--genre', a.genre,
            '--split-seed', str(a.split_seed), '--test-fraction', str(a.test_fraction),
            '--min-words', str(a.min_words), '--out', pool_out]))
        nxt = ['python', '-m', 'experiments.g02_generate', '--notes', a.out, '--pool', pool_out,
               '--out', os.path.join(os.path.dirname(a.out), 'g02_generations.jsonl')]
        if a.sections_out:
            nxt += ['--originals', a.sections_out]
        nxt += ['--expected-sections', str(len(sections))]
        if a.model_url:
            nxt += ['--model-url', a.model_url, '--model-name', a.model_name]
        print('next: ' + shlex.join(nxt))
    print(json.dumps({'selected': len(sections), 'written': len(written),
                      'records': review['n_records'], 'flagged': len(review['flagged'])}))
    return 0 if complete else 1


if __name__ == '__main__':
    sys.exit(main())

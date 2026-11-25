"""AN-01 keyboard-driven annotation tool over an AN-02 manifest.

``resolve_items(manifest, documents, genre, *, only=None)`` — stable API (G-01.4
consumes it). Streams ``(doc_id, markdown)`` pairs, which must arrive in the
manifest's document order (documents not in the manifest are skipped), and
yields per manifest entry ``{sentence_id, doc_id, section_type, text,
context: {heading, previous, next}}`` where previous/next are the neighbouring
sentences within the same section (``None`` at section edges). Ids come from
``annotation_sample.document_sentences`` (the manifest's own computation).
Raises ``AnnotateError`` if the manifest's genre version key differs from
``genre`` or a manifest id is not found (named). Memory: manifest ids plus the
current document's sentences.

``AnnotationSession`` shows one sentence at a time; number keys pick a move,
``o`` other, ``u`` undo/relabel previous, ``s`` skip, ``q`` quit. Each answer is
appended to the ``AnnotationStore`` immediately. On start it skips items this
annotator already labelled in this pass under the current version key.

Passes: ``first`` (AN-03, all entries) and ``repeat`` (AN-04, manifest
``repeat`` ids). Records carry ``pass``; this module's readers (``export``,
``labels_for_pass``, session resume) keep passes and annotators apart.
``AnnotationStore.read()`` does not: it keeps one latest record per sentence
across passes and annotators, so a repeat label hides the first-pass one
there. Consumers needing a pass use ``labels_for_pass`` or ``export``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from experiments.annotation_sample import document_sentences, heading_map
from service.annotation_store import OTHER, AnnotationStore
from service.genre import labels_valid_for, load_genre, version_key

PASSES = ('first', 'repeat')


class AnnotateError(ValueError):
    """Manifest, corpus or genre do not line up."""


def _check_version(manifest, genre):
    if manifest.get('genre') != version_key(genre):
        raise AnnotateError(
            f'manifest genre key {manifest.get("genre")!r} != {version_key(genre)!r}; '
            're-draw the sample or use the genre file it was drawn under')


def pass_ids(manifest, pass_name):
    if pass_name == 'first':
        return {e['sentence_id'] for e in manifest['entries']}
    if pass_name == 'repeat':
        return set(manifest['repeat'])
    raise AnnotateError(f'unknown pass {pass_name!r}; expected one of {PASSES}')


def resolve_items(manifest, documents, genre, *, only=None):
    _check_version(manifest, genre)
    wanted: dict[str, list[str]] = {}
    for e in manifest['entries']:
        if only is None or e['sentence_id'] in only:
            wanted.setdefault(e['doc_id'], []).append(e['sentence_id'])
    order = list(wanted)
    headings = heading_map(genre)
    pos = 0
    for doc_id, markdown in documents:
        if doc_id not in wanted:
            continue
        if order.index(doc_id) != pos:
            raise AnnotateError(f'document {doc_id!r} out of manifest order '
                                f'(expected {order[pos]!r})')
        pos += 1
        sents = document_sentences(doc_id, markdown, headings)
        index = {s['sentence_id']: i for i, s in enumerate(sents)}
        for sid in wanted[doc_id]:
            if sid not in index:
                raise AnnotateError(f'manifest sentence id {sid!r} not found in {doc_id!r}')
            i = index[sid]
            s = sents[i]
            same = lambda j: 0 <= j < len(sents) and \
                sents[j]['section_index'] == s['section_index']
            yield {'sentence_id': sid, 'doc_id': doc_id, 'section_type': s['section_type'],
                   'text': s['text'],
                   'context': {'heading': s['heading'],
                               'previous': sents[i - 1]['text'] if same(i - 1) else None,
                               'next': sents[i + 1]['text'] if same(i + 1) else None}}
    if pos < len(order):
        missing = order[pos]
        raise AnnotateError(f'document {missing!r} not in corpus; manifest sentence id '
                            f'{wanted[missing][0]!r} not found')


def _labelled(store, genre, pass_name, annotator=None):
    """Latest current-version record per (sentence_id, annotator) for a pass, write order."""
    latest = {}
    for _, obj in store._records():
        if (obj.get('genre') == genre['genre'] and labels_valid_for(genre, obj)
                and obj.get('pass') == pass_name
                and (annotator is None or obj.get('annotator') == annotator)):
            latest[(obj['sentence_id'], obj['annotator'])] = obj
    return latest


def labels_for_pass(store, genre, pass_name, annotator=None):
    """Current-version label records of one pass, latest per (sentence, annotator), write order.

    Unlike ``AnnotationStore.read()`` a repeat-pass label never hides a first-pass one.
    Needs no manifest. Production caller: G-01.6 (expert labels for g01); unwired until then.
    """
    if pass_name not in PASSES:
        raise AnnotateError(f'unknown pass {pass_name!r}; expected one of {PASSES}')
    return list(_labelled(store, genre, pass_name, annotator).values())


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class AnnotationSession:
    def __init__(self, items, store, genre, annotator, pass_name, *,
                 input_fn=input, output_fn=print, clock=_now):
        if pass_name not in PASSES:
            raise AnnotateError(f'unknown pass {pass_name!r}')
        self.items, self.store, self.genre = items, store, genre
        self.annotator, self.pass_name = annotator, pass_name
        self.input, self.output, self.clock = input_fn, output_fn, clock
        self.keys = {str(k): m['id'] for k, m in enumerate(genre['moves'], 1)}
        self.keys['o'] = OTHER

    def _show(self, it, n, total):
        c = it['context']
        lines = [f'--- {n}/{total}  [{it["section_type"]}] {c["heading"] or "(no heading)"}']
        if c['previous']:
            lines.append(f'    {c["previous"]}')
        lines.append(f' >> {it["text"]}')
        if c['next']:
            lines.append(f'    {c["next"]}')
        lines.append('  '.join(f'[{k}] {v}' for k, v in self.keys.items()))
        lines.append('[u] undo  [s] skip  [q] quit')
        self.output('\n'.join(lines))

    def run(self):
        done = {sid for sid, _ in _labelled(self.store, self.genre, self.pass_name,
                                            self.annotator)}
        pending = [it for it in self.items if it['sentence_id'] not in done]
        i, stack, written = 0, [], 0
        while i < len(pending):
            it = pending[i]
            self._show(it, i + 1, len(pending))
            try:
                key = self.input('> ').strip().lower()
            except EOFError:
                break
            if key == 'q':
                break
            if key == 's':
                i += 1
            elif key == 'u':
                if stack:
                    i = stack.pop()
                else:
                    self.output('nothing to undo')
            elif key in self.keys:
                self.store.append(self.genre, {
                    'sentence_id': it['sentence_id'], 'label': self.keys[key],
                    'annotator': self.annotator, 'timestamp': self.clock(),
                    'pass': self.pass_name, 'doc_id': it['doc_id'],
                    'section_type': it['section_type']})
                written += 1
                stack.append(i)
                i += 1
            else:
                self.output(f'unknown key {key!r}')
        self.output(f'{written} labels written this session')
        return written


def export(store, genre, manifest, pass_name, annotator=None):
    """Current label records of a pass in manifest order (store schema, no text)."""
    _check_version(manifest, genre)
    ids = pass_ids(manifest, pass_name)
    order = {e['sentence_id']: n for n, e in enumerate(manifest['entries'])}
    recs = [r for (sid, _), r in _labelled(store, genre, pass_name, annotator).items()
            if sid in ids]
    return sorted(recs, key=lambda r: (order[r['sentence_id']], r['annotator']))


def load_documents(root, manifest):
    """Yield ``(doc_id, text)`` for each manifest document under ``root``, in manifest order."""
    seen = []
    for e in manifest['entries']:
        if not seen or seen[-1] != e['doc_id']:
            seen.append(e['doc_id'])
    for doc_id in seen:
        path = root / doc_id
        if not path.is_file():
            raise AnnotateError(f'document {doc_id!r} not in corpus')
        yield doc_id, path.read_text(encoding='utf-8')


_documents = load_documents  # backwards-compatible alias


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--manifest', required=True)
    p.add_argument('--corpus', required=True)
    p.add_argument('--genre', required=True)
    p.add_argument('--store', required=True)
    p.add_argument('--annotator', required=True)
    p.add_argument('--pass', dest='pass_name', choices=PASSES, default='first')
    p.add_argument('--export', metavar='OUT')
    args = p.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    genre = load_genre(args.genre)
    store = AnnotationStore(args.store)
    try:
        if args.export:
            recs = export(store, genre, manifest, args.pass_name, args.annotator)
            with open(args.export, 'w', encoding='utf-8') as fh:
                for r in recs:
                    fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n')
            print(f'wrote {args.export}: {len(recs)} records')
            return 0
        root = Path(args.corpus)
        if not root.is_dir():
            p.error(f'corpus directory not found: {root}')
        items = resolve_items(manifest, load_documents(root, manifest), genre,
                              only=pass_ids(manifest, args.pass_name))
        AnnotationSession(list(items), store, genre, args.annotator, args.pass_name).run()
    except AnnotateError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

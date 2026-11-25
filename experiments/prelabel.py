"""G-01.4 LLM pre-label runner: one label per sentence from the genre inventory or ``other``.

Input items (``PrelabelItem``) are the shape AN-01's ``resolve_items`` yields; until that is wired
the CLI reads them from an items JSONL. ``model`` is any callable ``prompt -> reply``; its
``model_id`` attribute (default ``"unknown"``) is recorded. Each prompt holds only the inventory
(move id, name, definition), ``other``, the sentence's section type, its own context and its text:
never another report's text.

Output: one JSONL record per sentence, appended and flushed as produced:
  {sentence_id, doc_id, label, invalid_reply, attempts, model, prompt_hash,
   genre_version, genre_hash}
``llm_labels(records)`` gives the ``sentence_id -> label`` map that experiments.gates.g01 takes
as ``config["llm"]``. A reply that does not name exactly one valid label is retried up to
``max_retries`` times, then recorded as ``other`` with ``invalid_reply: true``.

Resumable: ids already in ``out_path`` under the same genre version key and model are skipped.
Memory: O(labelled ids) for the resume set; items are streamed one prompt at a time.

Production caller: the CLI run for G-01.6. ``local_model`` is unwired by default (no model ships);
it posts to a loopback OpenAI-compatible endpoint gated by service.network_guard.check_url (I9).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from typing import Callable, Iterable, Iterator, TypedDict

from service.genre import OTHER, load_genre, version_key
from service.network_guard import NetworkPolicy, check_url


class PrelabelItem(TypedDict):
    """One sentence to label (AN-01 ``resolve_items`` shape)."""
    sentence_id: str
    doc_id: str
    section_type: str
    text: str
    context: str


Model = Callable[[str], str]


def valid_labels(genre) -> list:
    return [m['id'] for m in genre['moves']] + [OTHER]


def build_prompt(item: PrelabelItem, genre) -> str:
    lines = ['Label the TARGET sentence with exactly one move id from this inventory.', '']
    for m in genre['moves']:
        lines.append(f"- {m['id']}: {m['name']}. {m['definition']}")
    lines.append(f'- {OTHER}: none of the moves above applies.')
    lines += ['', f"Section type: {item.get('section_type') or 'unknown'}",
              f"Context: {item.get('context') or ''}",
              f"TARGET: {item['text']}", '',
              'Reply with the move id only.']
    return '\n'.join(lines)


def parse_reply(reply, labels) -> str | None:
    """The single valid label the reply names, else None (empty, unknown or ambiguous)."""
    if not isinstance(reply, str):
        return None
    tokens = set(re.findall(r'[A-Za-z0-9_\-]+', reply.lower()))
    found = [lab for lab in labels if lab.lower() in tokens]
    return found[0] if len(found) == 1 else None


def _done_ids(out_path, key, model_id) -> set:
    done = set()
    if not os.path.exists(out_path):
        return done
    with open(out_path, encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if (r.get('model') == model_id and r.get('genre_version') == key['genre_version']
                    and r.get('genre_hash') == key['genre_hash']):
                done.add(r['sentence_id'])
    return done


def iter_prelabel(items: Iterable[PrelabelItem], genre, model: Model, *, out_path,
                  max_retries: int = 2) -> Iterator[dict]:
    key = version_key(genre)
    model_id = getattr(model, 'model_id', 'unknown')
    labels = valid_labels(genre)
    done = _done_ids(out_path, key, model_id)
    with open(out_path, 'a', encoding='utf-8') as fh:
        for item in items:
            sid = item['sentence_id']
            if sid in done:
                continue
            prompt = build_prompt(item, genre)
            label, attempts = None, 0
            while label is None and attempts <= max_retries:
                attempts += 1
                label = parse_reply(model(prompt), labels)
            rec = {'sentence_id': sid, 'doc_id': item.get('doc_id'),
                   'label': label or OTHER, 'invalid_reply': label is None,
                   'attempts': attempts, 'model': model_id,
                   'prompt_hash': hashlib.sha256(prompt.encode('utf-8')).hexdigest(), **key}
            fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + '\n')
            fh.flush()
            done.add(sid)
            yield rec


def prelabel(items, genre, model, *, out_path, max_retries: int = 2) -> list:
    """Label every new item; returns the records written by this call."""
    return list(iter_prelabel(items, genre, model, out_path=out_path, max_retries=max_retries))


def llm_labels(records) -> dict:
    """sentence_id -> label map for g01 ``config["llm"]``."""
    return {r['sentence_id']: r['label'] for r in records}


def summarize(items, records) -> dict:
    """Row check: every input id has exactly one label; plus label counts and invalid replies."""
    ids = [i['sentence_id'] for i in items]
    per_id = Counter(r['sentence_id'] for r in records)
    missing = sorted(s for s in set(ids) if per_id[s] == 0)
    duplicates = sorted(s for s, n in per_id.items() if n > 1)
    return {'n_items': len(set(ids)), 'n_records': len(records),
            'counts': dict(Counter(r['label'] for r in records)),
            'invalid_replies': sum(1 for r in records if r.get('invalid_reply')),
            'missing': missing, 'duplicates': duplicates,
            'exactly_one_label_each': not missing and not duplicates}


def local_model(base_url: str, *, model: str = 'local', timeout: float = 120.0,
                policy: NetworkPolicy = NetworkPolicy()) -> Model:
    """Callable for a local OpenAI-compatible /chat/completions endpoint (loopback only)."""
    url = base_url.rstrip('/') + '/chat/completions'
    check_url(url, policy)

    def call(prompt: str) -> str:
        body = json.dumps({'model': model, 'temperature': 0,
                           'messages': [{'role': 'user', 'content': prompt}]}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        return data['choices'][0]['message']['content']

    call.model_id = model
    return call


def _read_items(path) -> Iterator[PrelabelItem]:
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m experiments.prelabel')
    ap.add_argument('--items', required=True)
    ap.add_argument('--genre', required=True)
    ap.add_argument('--model-url', required=True)
    ap.add_argument('--model-name', default='local')
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-retries', type=int, default=2)
    a = ap.parse_args(argv)
    genre = load_genre(a.genre)
    model = local_model(a.model_url, model=a.model_name)
    prelabel(_read_items(a.items), genre, model, out_path=a.out, max_retries=a.max_retries)
    key = version_key(genre)
    with open(a.out, encoding='utf-8') as fh:
        recs = [r for r in map(json.loads, filter(str.strip, fh))
                if r.get('model') == model.model_id and r.get('genre_hash') == key['genre_hash']
                and r.get('genre_version') == key['genre_version']]
    summary = summarize(list(_read_items(a.items)), recs)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary['exactly_one_label_each'] else 1


if __name__ == '__main__':
    sys.exit(main())

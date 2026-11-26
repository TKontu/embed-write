"""G-01.5 build the experiments.gates.g01 config from stored annotations and LLM pre-labels.

``build_config(store, genre, manifest, prelabel_path, *, annotator=None, model_id=None)``
returns ``{expert, [expert_repeat], llm, labels, other_label, doc_of}``:

* ``expert`` / ``expert_repeat``: ``annotate.labels_for_pass`` for the ``first`` / ``repeat``
  pass, restricted to ``annotate.pass_ids(manifest, pass)``. Retracted (undone) labels are absent.
  ``expert_repeat`` is omitted when the repeat pass has no labels.
* ``llm``: ``prelabel.llm_labels`` over the prelabel JSONL records under the genre's version key
  (and ``model_id`` when given), restricted to first-pass ids. The file is streamed; a torn or
  unparsable line is skipped as prelabel resume does.
* ``labels``: ``prelabel.valid_labels(genre)`` order; ``other_label``: ``'other'``;
  ``doc_of``: sentence_id -> doc_id from the manifest entries.

Raises ``annotate.AnnotateError`` on a manifest/genre version mismatch and ``G01InputsError`` on
two labels for one id under one model, or for one id from two models/annotators when no
``model_id``/``annotator`` selects one (the g01 maps hold one label per id).

Memory: maps are O(manifest sample size); the store and prelabel file are streamed.

Production caller: the G-01.6 result run. Unwired by design until then (G-01.6 wires it).

CLI: ``python -m experiments.g01_inputs --store S --genre G --manifest M --prelabel P
[--annotator A] [--model-id ID] --out CONFIG.json`` writes the config (label maps only) and prints
counts.
"""
from __future__ import annotations

import argparse
import json
import sys

from experiments import annotate, prelabel
from service.annotation_store import AnnotationStore
from service.genre import OTHER, load_genre, version_key


class G01InputsError(ValueError):
    """Stored labels cannot form one-label-per-id g01 maps."""


def _expert(store, genre, manifest, pass_name, annotator):
    ids = annotate.pass_ids(manifest, pass_name)
    out = {}
    for r in annotate.labels_for_pass(store, genre, pass_name, annotator):
        sid = r['sentence_id']
        if sid not in ids:
            continue
        if sid in out:
            raise G01InputsError(
                f'{pass_name}-pass sentence {sid!r} labelled by several annotators; '
                'pass --annotator')
        out[sid] = r['label']
    return out


def _llm_records(prelabel_path, genre, model_id, ids):
    key = version_key(genre)
    seen = {}
    for r in prelabel._parsed_lines(prelabel_path):
        if not isinstance(r, dict) or 'sentence_id' not in r:
            continue
        if any(r.get(k) != v for k, v in key.items()):
            continue
        if model_id is not None and r.get('model') != model_id:
            continue
        sid = r['sentence_id']
        if sid not in ids:
            continue
        if sid in seen:
            if seen[sid] == r.get('model'):
                raise G01InputsError(
                    f'duplicate LLM label for {sid!r} under model {seen[sid]!r}')
            raise G01InputsError(
                f'LLM labels for {sid!r} from model {seen[sid]!r} and {r.get("model")!r}; '
                'pass model_id / --model-id')
        seen[sid] = r.get('model')
        yield r


def build_config(store, genre, manifest, prelabel_path, *, annotator=None, model_id=None) -> dict:
    annotate._check_version(manifest, genre)
    first = annotate.pass_ids(manifest, 'first')
    cfg = {'expert': _expert(store, genre, manifest, 'first', annotator)}
    repeat = _expert(store, genre, manifest, 'repeat', annotator)
    if repeat:
        cfg['expert_repeat'] = repeat
    cfg['llm'] = prelabel.llm_labels(_llm_records(prelabel_path, genre, model_id, first))
    cfg['labels'] = prelabel.valid_labels(genre)
    cfg['other_label'] = OTHER
    cfg['doc_of'] = {e['sentence_id']: e['doc_id'] for e in manifest['entries']}
    return cfg


def counts(cfg) -> dict:
    return {'n expert': len(cfg['expert']), 'n repeat': len(cfg.get('expert_repeat', {})),
            'n llm': len(cfg['llm']), 'n paired': len(cfg['expert'].keys() & cfg['llm'].keys())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--store', required=True)
    ap.add_argument('--genre', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--prelabel', required=True)
    ap.add_argument('--annotator')
    ap.add_argument('--model-id')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    genre = load_genre(a.genre)
    with open(a.manifest, encoding='utf-8') as fh:
        manifest = json.load(fh)
    try:
        cfg = build_config(AnnotationStore(a.store), genre, manifest, a.prelabel,
                           annotator=a.annotator, model_id=a.model_id)
    except (annotate.AnnotateError, G01InputsError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write('\n')
    for k, v in counts(cfg).items():
        print(f'{k}: {v}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

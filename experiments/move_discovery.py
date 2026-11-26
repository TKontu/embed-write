"""MV-02: move-discovery support — cluster sentence embeddings per section type.

This is a **suggestion for the expert**, never an inventory: it writes a JSON
cluster report (per section type: cluster sizes and the example sentences
nearest each centroid, optionally an LLM-proposed name and definition). Choosing
moves, definitions and examples stays with the expert (MV-03/MV-04, ``[H]``).

Sentences and section types come from ``experiments.annotation_sample.
document_sentences``; ``unknown`` (text before any ATX heading or under an
unmapped heading) is kept as its own section type. Documents stream through
``experiments.corpus.iter_documents``. Each section type keeps a seeded
reservoir sample of at most ``max_per_type`` sentences (texts only), so memory
and embedding work are bounded by that cap, not by the corpus. Only the retained
texts are embedded, in batches of 64 through ``service.embedder.embed``; the
CLI's default ``HashEmbedder`` is development-only and the report says so.

Clustering is a stdlib k-means with k-means++ seeding on L2-normalised vectors
(cosine similarity), a fixed iteration cap and a seeded RNG, so a seed
reproduces a report. ``k`` is clipped per section type to the sample size.
Names are optional: pass ``model`` (a callable ``prompt -> reply``, e.g.
``experiments.prelabel.local_model``, which enforces the network guard). A
strict JSON reply (an object with exactly non-empty string ``name`` and
``definition``) fills ``name``/``definition`` with ``proposed_by: "LLM"``; any
other reply or a raising model leaves them null with an ``error`` string and
never aborts the report. Reports are LLM-built suggestions and are not validated
against the corpus.

Unwired by design: the CLI is the production entry point; the operator runs it
on the private corpus to prepare MV-03.

CLI: python -m experiments.move_discovery report CORPUS_DIR GENRE.json OUT.json
     [--k N] [--max-per-type M] [--examples E] [--seed S]
     [--model-url URL] [--model-name NAME] [--force]
     [--embedder hash | --embedder onnx --model-dir DIR [--candidate bge-m3]]

``--embedder onnx`` loads ``service.candidates.OnnxEmbedder`` (CPU onnxruntime)
from a local DIR holding model.onnx and tokenizer.json (see
``scripts/export_onnx.py``); nothing is downloaded. A missing DIR or file exits
2 before any document is read.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

from experiments.annotation_sample import document_sentences, heading_map
from experiments.corpus import iter_documents
from experiments.prelabel import local_model
from service.candidates import CANDIDATES, OnnxEmbedder
from service.embedder import HashEmbedder, embed
from service.genre import load_genre, version_key
from service.normalize import l2_normalize
from service.vectors import Level

SCHEMA_VERSION = 1
DEFAULT_K = 8
DEFAULT_MAX_PER_TYPE = 2000
DEFAULT_EXAMPLES = 5
DEFAULT_SEED = 0
MAX_ITERATIONS = 100
EMBED_BATCH = 64
MEMORY_BOUND = ('O(max_per_type) sampled sentence texts and vectors per section type; '
                'one document text at a time; no corpus-sized vector set')

Model = Callable[[str], str]

_NOTE = ('LLM-built discovery suggestion for MV-03 [H]: clusters are candidates, not an '
         'inventory, and no move is chosen here.')
_NAMING_RULES = ('Reply with strict JSON only: an object with exactly the keys "name" and '
                 '"definition", both non-empty strings. No Markdown fences, no commentary.')


class DiscoveryError(ValueError):
    """The discovery input or an intermediate result is unusable."""


def _validate(k, max_per_type, examples, seed):
    if type(k) is not int or k < 1:
        raise DiscoveryError('k must be a positive integer')
    if type(max_per_type) is not int or max_per_type < 1:
        raise DiscoveryError('max_per_type must be a positive integer')
    if type(examples) is not int or examples < 0:
        raise DiscoveryError('examples must be a non-negative integer')
    if type(seed) is not int:
        raise DiscoveryError('seed must be an integer')


def sample_section_type(documents: Iterable[tuple[str, str]], genre, *, max_per_type: int,
                        seed: int) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Seeded reservoir sample per section type.

    Returns ``({type: [item...]}, {type: seen_count})`` where item is
    ``{doc_id, sentence_id, text}``. Retains at most ``max_per_type`` items per
    type, independent of the number of documents; documents are never held.
    Retained items are sorted by ``(doc_id, sentence_id)`` so later stages do not
    depend on reservoir internals.
    """
    if type(max_per_type) is not int or max_per_type < 1:
        raise DiscoveryError('max_per_type must be a positive integer')
    headings = heading_map(genre)
    rngs: dict[str, random.Random] = {}
    samples: dict[str, list[dict]] = {}
    seen: Counter = Counter()
    for doc_id, markdown in documents:
        for row in document_sentences(doc_id, markdown, headings):
            section_type = row['section_type']
            seen[section_type] += 1
            retained = samples.setdefault(section_type, [])
            item = {'doc_id': doc_id, 'sentence_id': row['sentence_id'], 'text': row['text']}
            if len(retained) < max_per_type:
                retained.append(item)
                continue
            rng = rngs.get(section_type)
            if rng is None:
                rng = rngs[section_type] = random.Random(f'{seed}:{section_type}')
            pick = rng.randrange(seen[section_type])
            if pick < max_per_type:
                retained[pick] = item
    for retained in samples.values():
        retained.sort(key=lambda item: (item['doc_id'], item['sentence_id']))
    return samples, dict(seen)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.fsum(x * y for x, y in zip(a, b))


def _mean_centroid(vectors, members):
    mean = [math.fsum(vectors[i][d] for i in members) / len(members)
            for d in range(len(vectors[members[0]]))]
    try:
        return tuple(l2_normalize(mean))
    except ValueError as exc:
        raise DiscoveryError(f'cluster centroid cannot be normalised: {exc}') from exc


def _init_centroids(vectors, k, rng):
    """k-means++ seeding with cosine distance; deterministic for ``rng``."""
    n = len(vectors)
    chosen = [rng.randrange(n)]
    distance = [max(0.0, 1.0 - _cosine(v, vectors[chosen[0]])) ** 2 for v in vectors]
    while len(chosen) < k:
        total = math.fsum(distance)
        if total <= 0.0:
            pick = rng.randrange(n)
        else:
            target = rng.random() * total
            pick, cumulative = n - 1, 0.0
            for index, weight in enumerate(distance):
                cumulative += weight
                if cumulative > target:
                    pick = index
                    break
        chosen.append(pick)
        centre = vectors[pick]
        distance = [min(distance[i], max(0.0, 1.0 - _cosine(vectors[i], centre)) ** 2)
                    for i in range(n)]
    return [vectors[index] for index in chosen]


def _assign(vectors, centroids):
    assignment = []
    for vector in vectors:
        best, best_similarity = 0, _cosine(vector, centroids[0])
        for index in range(1, len(centroids)):
            similarity = _cosine(vector, centroids[index])
            if similarity > best_similarity:
                best, best_similarity = index, similarity
        assignment.append(best)
    return assignment


def _update(vectors, assignment, centroids):
    groups: list[list[int]] = [[] for _ in centroids]
    for index, cluster in enumerate(assignment):
        groups[cluster].append(index)
    return [(_mean_centroid(vectors, members) if members else centroids[cluster])
            for cluster, members in enumerate(groups)]


def _kmeans(vectors, k, seed, section_type):
    """Cosine k-means; returns ``(assignment, centroids)``. Empty clusters keep their centre."""
    n = len(vectors)
    k = min(k, n)
    if n == 0:
        return [], []
    rng = random.Random(f'kmeans:{seed}:{section_type}')
    centroids = _init_centroids(vectors, k, rng)
    assignment = None
    for _ in range(MAX_ITERATIONS):
        updated = _assign(vectors, centroids)
        if updated == assignment:
            assignment = updated
            break
        assignment = updated
        centroids = _update(vectors, assignment, centroids)
    else:
        assignment = _assign(vectors, centroids)
    centroids = _update(vectors, assignment, centroids)
    return assignment, centroids


def _examples(items, vectors, members, centroid, limit):
    if not members or limit == 0:
        return []
    ranked = sorted(members,
                    key=lambda i: (-_cosine(vectors[i], centroid),
                                   items[i]['doc_id'], items[i]['sentence_id']))
    return [items[i]['text'] for i in ranked[:limit]]


def build_naming_prompt(section_type, examples, size):
    lines = ['A researcher is naming a cluster of sentences from one section type of a corpus.',
             f'Section type: {section_type}',
             f'Cluster size: {size}',
             'Example sentences:']
    lines.extend(f'- {example}' for example in examples)
    lines += ['',
              'Propose a short name for the rhetorical move these sentences suggest and a',
              'one-sentence definition. ' + _NAMING_RULES,
              '{"name": "...", "definition": "..."}']
    return '\n'.join(lines)


def parse_naming(reply) -> tuple[str, str]:
    """Strictly parse ``{"name": ..., "definition": ...}``; raise ValueError otherwise."""
    if not isinstance(reply, str):
        raise ValueError('reply must be a string')
    data = json.loads(reply)
    if not isinstance(data, dict):
        raise ValueError('reply must be a JSON object')
    if set(data) != {'name', 'definition'}:
        raise ValueError('reply must have exactly the keys "name" and "definition"')
    name, definition = data['name'], data['definition']
    for key, value in (('name', name), ('definition', definition)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{key} must be a non-empty string')
    return name.strip(), definition.strip()


def _name_clusters(clusters, model, section_type):
    """Fill naming fields in place. One model call per non-empty cluster."""
    for cluster in clusters:
        cluster['name'] = None
        cluster['definition'] = None
        cluster['proposed_by'] = None
        cluster['error'] = None
    if model is None:
        return
    for cluster in clusters:
        if cluster['size'] == 0:
            continue  # nothing to name; reported as a size-0 cluster
        prompt = build_naming_prompt(section_type, cluster['examples'], cluster['size'])
        try:
            name, definition = parse_naming(model(prompt))
        except Exception as exc:  # a bad or failing model must not abort the report
            cluster['error'] = f'{type(exc).__name__}: {exc}'
            continue
        cluster['name'] = name
        cluster['definition'] = definition
        cluster['proposed_by'] = 'LLM'


def build_report(corpus_dir, genre, *, embedder, k: int = DEFAULT_K,
                 max_per_type: int = DEFAULT_MAX_PER_TYPE, examples: int = DEFAULT_EXAMPLES,
                 seed: int = DEFAULT_SEED, model: Model | None = None) -> dict:
    """Build the cluster report; corpus documents are streamed and never retained.

    Raises DiscoveryError for invalid arguments and FileNotFoundError when
    ``corpus_dir`` is not a directory.
    """
    _validate(k, max_per_type, examples, seed)
    root = Path(corpus_dir)
    if not root.is_dir():
        raise FileNotFoundError(f'corpus directory not found: {root}')
    documents = ((document.path.relative_to(root).as_posix(), document.text)
                 for document in iter_documents(root))
    samples, seen = sample_section_type(documents, genre, max_per_type=max_per_type, seed=seed)

    clusters_by_type: dict[str, list[dict]] = {}
    sections: dict[str, dict] = {}
    for section_type in sorted(samples):
        items = samples[section_type]
        vectors = [tuple(l2_normalize(vector.values))
                   for vector in embed(embedder, [item['text'] for item in items],
                                       Level.SENTENCE, batch_size=EMBED_BATCH)]
        k_effective = min(k, len(items))
        assignment, centroids = _kmeans(vectors, k_effective, seed, section_type)
        groups: list[list[int]] = [[] for _ in range(k_effective)]
        for index, cluster in enumerate(assignment):
            groups[cluster].append(index)
        order = sorted(range(k_effective),
                       key=lambda c: (-len(groups[c]),
                                      groups[c][0] if groups[c] else len(items), c))
        clusters = []
        for cluster_id, group in enumerate(order):
            members = groups[group]
            clusters.append({
                'cluster_id': cluster_id,
                'size': len(members),
                'examples': _examples(items, vectors, members, centroids[group], examples),
                'name': None,
                'definition': None,
                'proposed_by': None,
                'error': None,
            })
        _name_clusters(clusters, model, section_type)
        clusters_by_type[section_type] = clusters
        sections[section_type] = {'seen': seen[section_type], 'sampled': len(items),
                                  'k': k_effective}

    development_only = isinstance(embedder, HashEmbedder)
    warnings = (['hash-stub is a development-only embedder; these clusters are not semantic']
                if development_only else [])
    model_id = getattr(model, 'model_id', None) if model is not None else None
    return {
        'schema_version': SCHEMA_VERSION,
        'note': _NOTE,
        'memory_bound': MEMORY_BOUND,
        'genre': version_key(genre),
        'embedder': {
            'model_id': embedder.model_id,
            'model_version': embedder.model_version,
            'dims': embedder.dims,
            'development_only': development_only,
        },
        'warnings': warnings,
        'k': k,
        'seed': seed,
        'examples': examples,
        'max_per_type': max_per_type,
        'sections': sections,
        'sentences': {'seen': sum(seen.values()),
                      'sampled': sum(len(items) for items in samples.values())},
        'naming': {'model': model_id, 'proposed_by': 'LLM' if model is not None else None},
        'clusters': clusters_by_type,
    }


def write_report(report, out, force: bool = False) -> None:
    """Write the report as sorted-key JSON; refuse to overwrite unless force."""
    data = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    with open(out, 'w' if force else 'x', encoding='utf-8') as handle:
        handle.write(data)


CANDIDATE_NAMES = {c.model_id.split('/')[-1]: c for c in CANDIDATES}
ONNX_FILES = ('model.onnx', 'tokenizer.json')


def make_embedder(name: str, model_dir: str | None = None, candidate: str = 'bge-m3'):
    """Build the CLI's embedder; raises DiscoveryError for a missing model_dir or file."""
    if name == 'hash':
        return HashEmbedder()
    if name != 'onnx':
        raise DiscoveryError(f'unknown embedder: {name}')
    if not model_dir:
        raise DiscoveryError('--embedder onnx needs --model-dir')
    if not Path(model_dir).is_dir():
        raise DiscoveryError(f'model directory not found: {model_dir}')
    for file_name in ONNX_FILES:
        if not (Path(model_dir) / file_name).is_file():
            raise DiscoveryError(f'missing {file_name} in model directory {model_dir}')
    if candidate not in CANDIDATE_NAMES:
        raise DiscoveryError(f'unknown candidate: {candidate}')
    return OnnxEmbedder(CANDIDATE_NAMES[candidate], model_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m experiments.move_discovery')
    sub = parser.add_subparsers(dest='cmd', required=True)
    command = sub.add_parser('report', help='write a cluster report over a Markdown corpus')
    command.add_argument('corpus')
    command.add_argument('genre')
    command.add_argument('out')
    command.add_argument('--k', type=int, default=DEFAULT_K,
                         help=f'clusters per section type (default {DEFAULT_K}; clipped to sample)')
    command.add_argument('--max-per-type', type=int, default=DEFAULT_MAX_PER_TYPE,
                         help=f'sentences sampled per section type (default {DEFAULT_MAX_PER_TYPE})')
    command.add_argument('--examples', type=int, default=DEFAULT_EXAMPLES,
                         help=f'example sentences per cluster (default {DEFAULT_EXAMPLES})')
    command.add_argument('--seed', type=int, default=DEFAULT_SEED,
                         help=f'sampling and k-means seed (default {DEFAULT_SEED})')
    command.add_argument('--model-url', default=None,
                         help='loopback OpenAI-compatible endpoint for cluster naming')
    command.add_argument('--model-name', default=None,
                         help='model name sent to --model-url (default "local")')
    command.add_argument('--embedder', choices=('hash', 'onnx'), default='hash',
                         help='hash is a development-only stub, not a semantic model; '
                              'onnx runs a local model from --model-dir')
    command.add_argument('--model-dir', default=None,
                         help='directory with model.onnx and tokenizer.json (--embedder onnx)')
    command.add_argument('--candidate', choices=sorted(CANDIDATE_NAMES), default='bge-m3',
                         help='candidate model record for --embedder onnx (default bge-m3)')
    command.add_argument('--force', action='store_true', help='overwrite an existing OUT')
    args = parser.parse_args(argv)
    if args.model_name and not args.model_url:
        parser.error('--model-name needs --model-url')
    if args.embedder != 'onnx' and args.model_dir:
        parser.error('--model-dir needs --embedder onnx')
    try:
        embedder = make_embedder(args.embedder, args.model_dir, args.candidate)
    except DiscoveryError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    if not Path(args.corpus).is_dir():
        print(f'error: corpus directory not found: {args.corpus}', file=sys.stderr)
        return 2
    if Path(args.out).exists() and not args.force:
        print(f'error: {args.out} exists; use --force to overwrite', file=sys.stderr)
        return 1
    try:
        genre = load_genre(args.genre)
        model = (local_model(args.model_url, model=args.model_name or 'local')
                 if args.model_url else None)
        report = build_report(args.corpus, genre, embedder=embedder, k=args.k,
                              max_per_type=args.max_per_type, examples=args.examples,
                              seed=args.seed, model=model)
        write_report(report, args.out, force=args.force)
    except PermissionError as exc:  # network guard: fail closed before writing anything
        print(f'error: {exc}', file=sys.stderr)
        return 2
    except FileExistsError:
        print(f'error: {args.out} exists; use --force to overwrite', file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    sections = len(report['sections'])
    print(f"wrote {args.out}: {sections} section types, "
          f"{report['sentences']['sampled']} of {report['sentences']['seen']} sentences sampled")
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Offline CA-05 benchmark; CLI caller only, unwired from the product by design.

LLM-built synthetic text, not corpus. HashEmbedder is a stdlib stub, not a
model: timings measure segmentation/chunking/cache overhead, not inference.
Streaming memory: one paragraph, one batch of texts/vectors, and at most
2048 segmentation-cache entries. Each VectorStore.put is one transaction.
"""
import argparse
from collections.abc import Iterator
import hashlib
import json
from pathlib import Path
import platform
import random
import tempfile
from time import perf_counter

from service.chunk import Block, chunk_blocks
from service.embedder import HashEmbedder, embed
from service.segcache import SegmentationCache
from service.segment import SEGMENTER_ID, segment_sentences
from service.vector_store import VectorKey, VectorStore
from service.vectors import Level

# Fixed vocabulary, sampled with stdlib random; no external word-list resource.
_WORDS = ('river forest meadow stone cloud field garden bridge path hill '
          'light water leaf wind seed root branch valley shore rain').split()


def _positive(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f'{name} must be a positive integer')


def synthetic_document(words=100_000, seed=0) -> Iterator[Block]:
    """Yield exact word count in 5–12 sentence paragraphs (last may be short)."""
    _positive(words, 'words')
    rng = random.Random(seed)
    remaining = words
    index = 0
    while remaining:
        sentences = []
        for _ in range(rng.randint(5, 12)):
            count = min(remaining, rng.randint(8, 16))
            sentence = ' '.join(rng.choice(_WORDS) for _ in range(count))
            sentences.append(sentence.capitalize() + '.')
            remaining -= count
            if not remaining:
                break
        yield Block(f'block-{index}', f'section-{index // 10}',
                    'paragraph', ' '.join(sentences))
        index += 1


def run_benchmark(store_path, *, words=100_000, seed=0, dims=32, batch_size=64) -> dict:
    """Measure empty-store and same-process warm passes; reject populated stores.

    Timings include synthetic generation, hashing and validated stub embedding
    (cold only), excluding store open/close and JSON output. store_bytes counts
    encoded live keys/values, not physical LMDB pages. Warm retains segcache.
    """
    _positive(words, 'words')
    _positive(batch_size, 'batch_size')
    backend = HashEmbedder(dims=dims)
    segcache = SegmentationCache(segment_sentences, 2048, key_version=SEGMENTER_ID)
    counts = {'words': 0, 'blocks': 0, 'sentences': 0, 'chunks': 0}
    with VectorStore(store_path) as store:
        if len(store):
            raise ValueError('cold benchmark requires an empty store')

        def flush(pending):
            # Each batch has a single level; deduplicate within the batch.
            if pending:
                keys = list(pending)
                vectors = embed(backend, list(pending.values()), keys[0].level,
                                batch_size=batch_size)
                for key, vector in zip(keys, vectors):
                    store.put(key, vector)
                pending.clear()

        def run(cold):
            pending = {}
            hits = 0
            for chunk in chunk_blocks(synthetic_document(words, seed), segcache):
                if cold:
                    counts['chunks'] += 1
                    if chunk.level is Level.BLOCK:
                        counts['blocks'] += 1
                        counts['words'] += len(chunk.text.split())
                    else:
                        counts['sentences'] += 1
                key = VectorKey(backend.model_id, backend.model_version, chunk.level,
                                hashlib.sha256(chunk.text.encode('utf-8')).hexdigest(), dims)
                if pending and next(iter(pending)).level is not key.level:
                    flush(pending)
                if store.get(key) is not None:
                    hits += 1
                elif cold:
                    pending[key] = chunk.text
                    if len(pending) == batch_size:
                        flush(pending)
                else:
                    raise RuntimeError('warm pass encountered a cache miss')
            flush(pending)
            return hits

        start = perf_counter()
        run(True)
        cold_seconds = perf_counter() - start
        start = perf_counter()
        warm_hits = run(False)
        warm_seconds = perf_counter() - start
        store_bytes = store.size_bytes()
    return {**counts, 'cold_seconds': cold_seconds, 'warm_seconds': warm_seconds,
            'warm_hits': warm_hits, 'store_bytes': store_bytes,
            'embedder': f'HashEmbedder ({backend.model_id}/{backend.model_version}, dims={dims})',
            'python': platform.python_version(), 'platform': platform.platform()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--words', type=int, default=100_000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ca05-store-') as tmp:
        result = run_benchmark(Path(tmp) / 'vectors', words=args.words)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

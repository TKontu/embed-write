// DM-04: seeded property-based fuzzing of the round-trip.
// Env: DOCMODEL_FUZZ_SEED (default 20261125), DOCMODEL_FUZZ_RUNS (default 500 per generator).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, serializeMarkdown } from '../src/index.js';
import { mulberry32, makeRand, genMarkdown, genDoc } from './fuzz-gen.js';

const SEED = Number(process.env.DOCMODEL_FUZZ_SEED ?? 20261125);
const RUNS = Number(process.env.DOCMODEL_FUZZ_RUNS ?? 500);
const json = (doc) => JSON.parse(JSON.stringify(doc.toJSON()));

/** Returns null when the round-trip properties hold, else a reason. @param {string} src */
function check(src) {
  try {
    const doc1 = parseMarkdown(src);
    const out1 = serializeMarkdown(doc1);
    const doc2 = parseMarkdown(out1);
    assert.deepEqual(json(doc2), json(doc1), 'parse -> serialize -> parse doc JSON equal');
    assert.equal(serializeMarkdown(doc2), out1, 'serialize fixed point');
    return null;
  } catch (e) {
    return e instanceof Error ? e.message.split('\n')[0] : String(e);
  }
}

/** Greedy line/block deletion shrinker: smallest input that still fails. @param {string} src */
function shrink(src) {
  let cur = src;
  for (const sep of ['\n\n', '\n']) {
    let changed = true;
    while (changed) {
      changed = false;
      const parts = cur.split(sep);
      for (let i = 0; i < parts.length && parts.length > 1; i++) {
        const cand = [...parts.slice(0, i), ...parts.slice(i + 1)].join(sep);
        if (check(cand)) { cur = cand; changed = true; break; }
      }
    }
  }
  return cur;
}

/** @param {string} label @param {(r: ReturnType<typeof makeRand>) => string} gen @param {number} salt */
function fuzz(label, gen, salt) {
  test(`fuzz ${label}: ${RUNS} cases, seed ${SEED}`, () => {
    const r = makeRand(mulberry32(SEED ^ salt));
    for (let i = 0; i < RUNS; i++) {
      const src = gen(r);
      const why = check(src);
      if (why) {
        const min = shrink(src);
        assert.fail(`${label} round-trip failed: seed=${SEED} case=${i}: ${why}\n--- minimal input ---\n${min}\n--- full input ---\n${src}`);
      }
    }
  });
}

fuzz('markdown', genMarkdown, 0);
fuzz('schema doc', (r) => serializeMarkdown(genDoc(r)), 0x5eed);

// Regression cases found by the fuzzer.
const REGRESSIONS = [
  ['leading thematic break is not front matter', '___\n\n***\n'],
  ['heading of only # is escaped once', '# \\#\n'],
];
for (const [name, src] of REGRESSIONS) {
  test(`fuzz regression: ${name}`, () => assert.equal(check(src), null));
}

test('prng is deterministic for a seed', () => {
  const a = makeRand(mulberry32(7)); const b = makeRand(mulberry32(7));
  assert.equal(genMarkdown(a), genMarkdown(b));
});

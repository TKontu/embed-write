import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Transform } from 'prosemirror-transform';
import {
  parseMarkdown, assignIds, schema, createSentenceLayer, hashText,
  sentenceIndex, resolveSentenceKey, parseSentenceKey,
} from '../src/index.js';

const MD = '# Head one. Head two.\n\nAa. Bb. Aa.\n\n- Item x. Item y.\n\n| A. B. | C. |\n| --- | --- |\n| D. | E. |\n\n```\nCode one. Code two.\n```\n';
const withIds = () => assignIds(parseMarkdown(MD));

test('index lists every sentence in doc order; resolve round-trips', () => {
  const doc = withIds();
  const before = JSON.stringify(doc.toJSON());
  const idx = sentenceIndex(doc);
  assert.deepEqual(idx.map((s) => s.text), [
    'Head one.', 'Head two.', 'Aa.', 'Bb.', 'Aa.', 'Item x.', 'Item y.',
    'A.', 'B.', 'C.', 'D.', 'E.', 'Code one.', 'Code two.',
  ]);
  assert.equal(new Set(idx.map((s) => s.key)).size, idx.length);
  for (const s of idx) {
    assert.equal(s.hash, hashText(s.text));
    const r = resolveSentenceKey(doc, s.key);
    assert.ok(r);
    assert.deepEqual(r, { blockId: s.blockId, pos: r.pos, index: s.index, start: s.start, end: s.end, text: s.text });
    assert.equal(doc.nodeAt(r.pos).attrs.id, s.blockId);
  }
  assert.equal(JSON.stringify(doc.toJSON()), before); // (h) not mutated
});

test('repeats get #1 and resolve to distinct offsets', () => {
  const doc = withIds();
  const aa = sentenceIndex(doc).filter((s) => s.text === 'Aa.');
  assert.match(aa[1].key, /#1$/);
  assert.ok(!aa[0].key.includes('#'));
  const [r0, r1] = aa.map((s) => resolveSentenceKey(doc, s.key));
  assert.notEqual(r0.start, r1.start);
  assert.equal(resolveSentenceKey(doc, `${aa[0].key}#2`), null); // repeat beyond count
});

test('null-id nodes are skipped', () => {
  assert.deepEqual(sentenceIndex(parseMarkdown(MD)), []);
  const p = (id, t) => schema.nodes.paragraph.create({ id }, schema.text(t));
  const doc = schema.nodes.doc.create(null, [p(null, 'No id.'), p('B1', 'Has id.')]);
  assert.deepEqual(sentenceIndex(doc).map((s) => s.blockId), ['B1']);
});

test('editing one sentence: old key null, siblings resolve', () => {
  const doc = withIds();
  const layer = createSentenceLayer();
  const idx = sentenceIndex(doc, layer);
  const bb = idx.find((s) => s.text === 'Bb.');
  const r = resolveSentenceKey(doc, bb.key, layer);
  const from = r.pos + 1 + r.start;
  const doc2 = new Transform(doc).replaceWith(from, from + 3, schema.text('Zz.')).doc;
  assert.equal(resolveSentenceKey(doc2, bb.key, layer), null);
  for (const s of idx.filter((x) => x.blockId === bb.blockId && x !== bb)) assert.ok(resolveSentenceKey(doc2, s.key, layer));
  assert.ok(sentenceIndex(doc2).some((s) => s.text === 'Zz.' && s.blockId === bb.blockId));
});

test('malformed keys: parse null, resolve null; missing block null', () => {
  const doc = withIds();
  for (const k of ['', 'nohash', ':h', 'b:', 'b:h#0', 'b:h#x', 'b:h#1#2', 'a:b:c', null, 42]) {
    assert.equal(parseSentenceKey(k), null, String(k));
    assert.equal(resolveSentenceKey(doc, /** @type {any} */ (k)), null);
  }
  assert.deepEqual(parseSentenceKey('B:h#3'), { blockId: 'B', hash: 'h', repeat: 3 });
  assert.equal(resolveSentenceKey(doc, `NOPE:${hashText('Aa.')}`), null);
});

test('fixture parity: sentences.js keys match sentence-keys.json', () => {
  const cases = JSON.parse(readFileSync(new URL('./fixtures/sentence-keys.json', import.meta.url), 'utf8'));
  assert.ok(cases.some((c) => c.keys.some((k) => k.includes('#'))));
  for (const c of cases) {
    assert.deepEqual(c.sentences.map(hashText), c.hashes);
    const segment = () => c.sentences;
    const node = schema.nodes.paragraph.create({ id: c.block_id }, c.sentences.length ? schema.text(c.sentences.join(' ')) : null);
    const keys = createSentenceLayer({ segment }).sentences(node, c.block_id).map((s) => s.key);
    assert.deepEqual(keys, c.keys);
  }
});

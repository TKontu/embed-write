import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, createSentenceLayer, normalizeText, hashText } from '../src/index.js';

const block = (md) => parseMarkdown(md).child(0);
const texts = (md, layer = createSentenceLayer()) => layer.sentences(block(md)).map((s) => s.text);

test('splitting cases', () => {
  assert.deepEqual(texts('One here. Two there. Three.\n'), ['One here.', 'Two there.', 'Three.']);
  assert.deepEqual(texts('See e.g. Smith. Dr. Who came. Fig. 3 shows i.e. It. No. 5 won.\n'),
    ['See e.g. Smith.', 'Dr. Who came.', 'Fig. 3 shows i.e. It.', 'No. 5 won.']);
  assert.deepEqual(texts('Pi is 3.14 today. Yes 2.5 M.\n'), ['Pi is 3.14 today.', 'Yes 2.5 M.']);
  assert.deepEqual(texts('Really? Yes! "Quoted" ok.\n'), ['Really?', 'Yes!', '"Quoted" ok.']);
  assert.deepEqual(texts('just one sentence without end\n'), ['just one sentence without end']);
  assert.deepEqual(createSentenceLayer().sentences(parseMarkdown('---\n').child(0)), []);
});

test('offsets slice normalized text; hash is hashText', () => {
  const node = block('Alpha  *beta*.   Gamma **delta**!\n');
  const norm = normalizeText(node);
  for (const s of createSentenceLayer().sentences(node)) {
    assert.equal(norm.slice(s.start, s.end), s.text);
    assert.equal(s.hash, hashText(s.text));
  }
});

test('repeat keys follow sentence_keys.py; null without blockId', () => {
  const layer = createSentenceLayer();
  const node = block('Aa. Aa. Bb. Aa.\n');
  const ss = layer.sentences(node, 'b1');
  const h = (t) => hashText(t);
  assert.deepEqual(ss.map((s) => s.key),
    [`b1:${h('Aa.')}`, `b1:${h('Aa.')}#1`, `b1:${h('Bb.')}`, `b1:${h('Aa.')}#2`]);
  assert.deepEqual(ss.map((s) => s.index), [0, 1, 2, 3]);
  assert.ok(layer.sentences(node).every((s) => s.key === null));
});

test('cache by hash; recompute after change; LRU eviction', () => {
  let calls = 0;
  const segment = (t) => { calls++; return t.split(/(?<=\.) /); };
  const layer = createSentenceLayer({ segment, maxEntries: 2 });
  layer.sentences(block('A. B.\n'), 'x');
  layer.sentences(block('A. *B*.\n'), 'y');
  assert.equal(calls, 1);
  layer.sentences(block('A. C.\n'));
  assert.equal(calls, 2);
  layer.sentences(block('D.\n'));
  assert.equal(layer.size, 2);
  layer.sentences(block('A. B.\n'));
  assert.equal(calls, 4);
});

test('nothing stored in doc', () => {
  const doc = parseMarkdown('One. Two.\n\nThree.\n');
  const before = JSON.stringify(doc.toJSON());
  const layer = createSentenceLayer();
  doc.forEach((n) => layer.sentences(n, 'id'));
  assert.equal(JSON.stringify(doc.toJSON()), before);
});

test('injected segmenter used', () => {
  const layer = createSentenceLayer({ segment: (t) => t.split(' ') });
  assert.deepEqual(layer.sentences(block('a b. c\n')).map((s) => [s.text, s.start]),
    [['a', 0], ['b.', 2], ['c', 5]]);
});

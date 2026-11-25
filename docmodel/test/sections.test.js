import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, sectionTree } from '../src/index.js';

// Compact shape: [level, text, blocks, children]
const shape = (s) => [s.level, s.heading?.text ?? null, s.blocks, s.children.map(shape)];
const tree = (md) => shape(sectionTree(parseMarkdown(md)));

test('flat h1/h2/h3 nesting', () => {
  assert.deepEqual(tree('# A\n\np\n\n## B\n\n### C\n\nq'),
    [0, null, [], [[1, 'A', [1], [[2, 'B', [], [[3, 'C', [4], []]]]]]]]);
});

test('skipped level h1 -> h3 nests directly under h1', () => {
  assert.deepEqual(tree('# A\n\n### C'), [0, null, [], [[1, 'A', [], [[3, 'C', [], []]]]]]);
});

test('document starting at h2 nests under root', () => {
  assert.deepEqual(tree('## B\n\n# A'), [0, null, [], [[2, 'B', [], []], [1, 'A', [], []]]]);
});

test('siblings and returning to a higher level', () => {
  assert.deepEqual(tree('# A\n\n## B\n\n## C\n\n### D\n\n# E\n\nx'),
    [0, null, [], [
      [1, 'A', [], [[2, 'B', [], []], [2, 'C', [], [[3, 'D', [], []]]]]],
      [1, 'E', [5], []],
    ]]);
});

test('no headings: all top-level blocks in root', () => {
  assert.deepEqual(tree('a\n\nb\n\n- c'), [0, null, [0, 1, 2], []]);
});

test('empty document', () => {
  assert.deepEqual(tree(''), [0, null, [], []]);
});

test('setext headings', () => {
  assert.deepEqual(tree('A\n===\n\nB\n---\n\nx'), [0, null, [], [[1, 'A', [], [[2, 'B', [2], []]]]]]);
});

test('content before first heading lands in root.blocks', () => {
  assert.deepEqual(tree('intro\n\n# A'), [0, null, [0], [[1, 'A', [], []]]]);
});

test('headings inside blockquotes or lists are not sections', () => {
  assert.deepEqual(tree('# A\n\n> # Q\n\n- # L'), [0, null, [], [[1, 'A', [1, 2], []]]]);
});

test('heading text is plain text content; index is top-level index', () => {
  const t = sectionTree(parseMarkdown('p\n\n# *Hello* **big** `world`'));
  assert.deepEqual(t.children[0].heading, { text: 'Hello big world', index: 1 });
});

test('does not mutate doc', () => {
  const doc = parseMarkdown('x\n\n# A\n\n## B\n\ny');
  const before = JSON.stringify(doc.toJSON());
  sectionTree(doc);
  assert.equal(JSON.stringify(doc.toJSON()), before);
});

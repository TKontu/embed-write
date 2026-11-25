import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, blockLayer } from '../src/index.js';

const kinds = (md) => blockLayer(parseMarkdown(md)).map((b) => b.kind);
const resolve = (doc, path) => path.reduce((n, i) => n.child(i), doc);

test('empty doc returns []', () => {
  assert.deepEqual(blockLayer(parseMarkdown('')), []);
});

test('covers each kind', () => {
  const md = '---\ntitle: x\n---\n\n# H\n\npara\n\n![alt](a.png)\n\n- item\n\n| a |\n| - |\n| b |\n\n'
    + '```js\ncode\n```\n\n> quote\n\n<div>x</div>\n\n---\n\nref[^1]\n\n[^1]: note\n';
  assert.deepEqual(kinds(md), ['front_matter', 'heading', 'paragraph', 'figure', 'list_item',
    'table', 'code', 'quote', 'html', 'thematic_break', 'paragraph', 'footnote']);
});

test('nested list items get own entries with correct paths', () => {
  const doc = parseMarkdown('- a\n  - b\n    1. c\n- d\n');
  const bl = blockLayer(doc);
  assert.deepEqual(bl.map((b) => [b.kind, b.text, b.path]), [
    ['list_item', 'abc', [0, 0]],
    ['list_item', 'bc', [0, 0, 1, 0]],
    ['list_item', 'c', [0, 0, 1, 0, 1, 0]],
    ['list_item', 'd', [0, 1]],
  ]);
});

test('blockquote containing a list is one quote entry', () => {
  assert.deepEqual(blockLayer(parseMarkdown('> - a\n> - b\n')).map((b) => [b.kind, b.path]),
    [['quote', [0]]]);
});

test('image-only paragraph is figure; image with text is paragraph', () => {
  assert.deepEqual(kinds('![x](y.png)\n\ntext ![x](y.png)\n'), ['figure', 'paragraph']);
});

test('section assignment: pre-heading null, skipped levels, innermost section', () => {
  const bl = blockLayer(parseMarkdown('intro\n\n# A\n\na\n\n### C\n\n- c\n\n# B\n\nb\n'));
  assert.deepEqual(bl.map((b) => [b.kind, b.text, b.section]), [
    ['paragraph', 'intro', null],
    ['heading', 'A', 1], ['paragraph', 'a', 1],
    ['heading', 'C', 3], ['list_item', 'c', 3],
    ['heading', 'B', 5], ['paragraph', 'b', 5],
  ]);
});

test('paths resolve to the entry node and doc is unchanged', () => {
  const doc = parseMarkdown('# T\n\n- a\n  - b\n\n> q\n\n| x |\n| - |\n| y |\n\n![i](j.png)\n');
  const before = JSON.stringify(doc.toJSON());
  const bl = blockLayer(doc);
  assert.ok(bl.length > 0);
  for (const b of bl) assert.equal(resolve(doc, b.path).textContent, b.text);
  for (const b of bl) {
    const n = resolve(doc, b.path);
    assert.ok(b.kind === 'figure' ? n.type.name === 'paragraph' : true);
  }
  assert.equal(JSON.stringify(doc.toJSON()), before);
});

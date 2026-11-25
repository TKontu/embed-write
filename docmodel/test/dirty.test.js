import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Transform } from 'prosemirror-transform';
import * as api from '../src/index.js';

const doc = (md) => api.assignIds(api.parseMarkdown(md));
const entries = (d) => {
  const found = [];
  d.descendants((node, pos) => found.push({ node, pos }));
  return found;
};
const ids = (...nodes) => new Set(nodes.map(n => n.attrs.id));

test('typing changes only its paragraph and id-bearing ancestors', () => {
  assert.equal(typeof api.dirtySet, 'function');
  for (const md of ['one\n\ntwo', '- one\n- two', '> one\n>\n> two']) {
    const d = doc(md);
    const target = entries(d).find(e => e.node.type.name === 'paragraph');
    const tr = new Transform(d).insert(target.pos + 2, api.schema.text('X'));
    const expected = new Set();
    const resolved = d.resolve(target.pos + 1);
    for (let depth = 1; depth <= resolved.depth; depth++) expected.add(resolved.node(depth).attrs.id);
    assert.deepEqual(api.dirtySet(tr), expected);
  }
});

test('table edits dirty only the cell, row and table', () => {
  const d = doc('| a | b |\n| - | - |\n| c | d |');
  const cell = entries(d).find(e => e.node.type.name === 'table_cell');
  const tr = new Transform(d).insert(cell.pos + 1, api.schema.text('X'));
  assert.deepEqual(api.dirtySet(tr), ids(d.firstChild, d.firstChild.firstChild, cell.node));
});

test('no-op and equal replacement have no dirty ids', () => {
  const d = doc('one\n\ntwo');
  assert.deepEqual(api.dirtySet(new Transform(d)), new Set());
  assert.deepEqual(api.dirtyRanges(new Transform(d)), []);
  const tr = new Transform(d).replaceWith(0, d.firstChild.nodeSize, d.firstChild);
  assert.deepEqual(api.dirtySet(tr), new Set());
});

test('separate edits map earlier ranges forward and leave other blocks clean', () => {
  const d = doc('one\n\ntwo\n\nthree');
  const tr = new Transform(d).insert(12, api.schema.text('X')).insert(2, api.schema.text('YY'));
  assert.deepEqual(api.dirtySet(tr), ids(d.firstChild, d.lastChild));
  assert.deepEqual(api.dirtyRanges(tr), [{ from: 2, to: 4 }, { from: 14, to: 15 }]);
});

test('overlapping and touching mapped ranges merge', () => {
  const d = doc('one');
  const tr = new Transform(d).insert(2, api.schema.text('X')).insert(3, api.schema.text('Y'));
  assert.deepEqual(api.dirtyRanges(tr), [{ from: 2, to: 4 }]);
});

test('deleting a block reports only its surviving parent', () => {
  for (const md of ['one\n\ntwo\n\nthree', '> one\n>\n> two\n>\n> three']) {
    const d = doc(md);
    const target = entries(d).filter(e => e.node.type.name === 'paragraph')[1];
    const tr = new Transform(d).delete(target.pos, target.pos + target.node.nodeSize);
    assert.deepEqual(api.dirtySet(tr), md.startsWith('>') ? ids(d.firstChild) : new Set());
    assert.deepEqual(api.dirtyRanges(tr), [{ from: target.pos, to: target.pos }]);
  }
});

test('inserting a fresh block reports it without touching adjacent siblings', () => {
  const d = doc('one\n\ntwo');
  const fresh = doc('new').firstChild;
  const tr = new Transform(d).insert(d.firstChild.nodeSize, fresh);
  assert.deepEqual(api.dirtySet(tr), ids(fresh));
});

test('markup-only edits report the node but not unchanged children', () => {
  const d = doc('> one\n>\n> two');
  const tr = new Transform(d).setNodeMarkup(0, undefined, { ...d.firstChild.attrs, id: 'fresh' });
  assert.deepEqual(api.dirtySet(tr), new Set(['fresh']));
  const p = doc('one\n\ntwo');
  const changed = new Transform(p).setNodeMarkup(0, api.schema.nodes.heading, { ...p.firstChild.attrs, level: 2 });
  assert.deepEqual(api.dirtySet(changed), ids(p.firstChild));
});

test('mark-only steps dirty their containing block despite empty maps and equal hashes', () => {
  const d = doc('one\n\ntwo');
  const tr = new Transform(d).addMark(1, 3, api.schema.marks.em.create());
  assert.deepEqual(api.dirtyRanges(tr), []);
  assert.deepEqual(api.dirtySet(tr), ids(d.firstChild));
  assert.equal(api.nodeHash(d.firstChild), api.nodeHash(tr.doc.firstChild));
});

test('null-id edited nodes report the nearest id-bearing ancestor', () => {
  const original = doc('> one\n>\n> two');
  const target = entries(original).find(e => e.node.type.name === 'paragraph');
  const d = new Transform(original).setNodeMarkup(target.pos, undefined, { ...target.node.attrs, id: null }).doc;
  const tr = new Transform(d).insert(target.pos + 1, api.schema.text('X'));
  assert.deepEqual(api.dirtySet(tr), ids(d.firstChild));
});

test('insertion then deletion back to the original leaves only the mapped point', () => {
  const d = doc('one\n\ntwo');
  const tr = new Transform(d).insert(2, api.schema.text('X')).delete(2, 3);
  assert.deepEqual(api.dirtySet(tr), new Set());
  assert.deepEqual(api.dirtyRanges(tr), [{ from: 2, to: 2 }]);
});

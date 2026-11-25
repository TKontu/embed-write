import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState } from 'prosemirror-state';
import * as api from '../src/index.js';

const { admitResult, filterFresh, nodeHash, schema } = api;
const doc = (md) => api.assignIds(api.parseMarkdown(md));
const paras = (d) => {
  const out = [];
  d.descendants((node, pos) => { if (node.type.name === 'paragraph') out.push({ node, pos }); });
  return out;
};
const resultFor = (node, extra = {}) => ({ nodeId: node.attrs.id, hash: nodeHash(node), ...extra });

test('(a) unchanged node is admitted', () => {
  const d = doc('one\n\ntwo');
  const r = resultFor(d.firstChild, { label: 'x' });
  assert.deepEqual(admitResult(d, r), { admitted: true });
  const out = filterFresh(d, [r]);
  assert.deepEqual(out.fresh, [r]);
  assert.deepEqual(out.discarded, []);
});

test('(b) text edit in node discards as changed', () => {
  const d = doc('one\n\ntwo');
  const r = resultFor(d.firstChild);
  const state = EditorState.create({ doc: d });
  const edited = state.apply(state.tr.insertText('X', 2)).doc;
  assert.equal(edited.firstChild.attrs.id, r.nodeId, 'id survives the edit');
  assert.deepEqual(admitResult(edited, r), { admitted: false, reason: 'changed' });
  assert.deepEqual(filterFresh(edited, [r]).discarded, [{ nodeId: r.nodeId, reason: 'changed' }]);
});

test('(c) mark-only edit is admitted because nodeHash ignores marks', () => {
  const d = doc('alpha beta\n');
  const r = resultFor(d.firstChild);
  const state = EditorState.create({ doc: d });
  const tr = state.tr.addMark(1, 6, schema.marks.strong.create());
  assert.notEqual(tr.doc.eq(d), true, 'the mark really changed the document');
  // Documented policy: formatting-only edits keep analysis results (marks are outside the hash).
  assert.deepEqual(admitResult(tr.doc, r), { admitted: true });
});

test('(d) deleted node discards as missing', () => {
  const d = doc('one\n\ntwo');
  const r = resultFor(d.firstChild);
  const state = EditorState.create({ doc: d });
  const after = state.apply(state.tr.delete(0, d.firstChild.nodeSize)).doc;
  assert.deepEqual(admitResult(after, r), { admitted: false, reason: 'missing' });
});

test('(e) malformed results discard without throwing', () => {
  const d = doc('one');
  const bad = [null, undefined, 42, 'x', {}, { hash: 'h' }, { nodeId: d.firstChild.attrs.id },
    { nodeId: '', hash: 'h' }, { nodeId: 7, hash: 'h' }, { nodeId: d.firstChild.attrs.id, hash: 3 }];
  for (const r of bad) assert.deepEqual(admitResult(d, r), { admitted: false, reason: 'malformed' });
  const out = filterFresh(d, bad);
  assert.equal(out.fresh.length, 0);
  assert.equal(out.counts.malformed, bad.length);
  assert.ok(out.discarded.every((x) => x.reason === 'malformed'));
  assert.deepEqual(filterFresh(d, null).fresh, []);
});

test('(f) edited node results drop while sibling results survive after a real transaction', () => {
  const d = doc('one\n\ntwo\n\nthree');
  const [p1, p2, p3] = paras(d);
  const results = [resultFor(p1.node, { k: 1 }), resultFor(p2.node, { k: 2 }),
    resultFor(p2.node, { k: 3 }), resultFor(p3.node, { k: 4 })];
  const state = EditorState.create({ doc: d });
  const next = state.apply(state.tr.insertText('X', p2.pos + 2));
  const out = filterFresh(next.doc, results);
  assert.deepEqual(out.fresh.map((r) => r.k), [1, 4]);
  assert.deepEqual(out.discarded, [{ nodeId: p2.node.attrs.id, reason: 'changed' },
    { nodeId: p2.node.attrs.id, reason: 'changed' }]);
  assert.deepEqual(out.counts, { missing: 0, changed: 2, malformed: 0 });
});

test('(g) filterFresh walks the doc once regardless of result count', () => {
  const d = doc(Array.from({ length: 50 }, (_, i) => `para ${i}`).join('\n\n'));
  const ps = paras(d);
  const results = Array.from({ length: 1000 }, (_, i) => resultFor(ps[i % ps.length].node, { i }));
  results.push({ nodeId: 'GONE', hash: 'h' });
  let walks = 0;
  const counting = new Proxy(d, {
    get(target, prop) {
      if (prop === 'descendants') return (...a) => { walks++; return target.descendants(...a); };
      const v = Reflect.get(target, prop, target);
      return typeof v === 'function' ? v.bind(target) : v;
    },
  });
  const out = filterFresh(counting, results);
  assert.equal(walks, 1);
  assert.equal(out.fresh.length, 1000);
  assert.deepEqual(out.fresh.map((r) => r.i), results.slice(0, 1000).map((r) => r.i));
  assert.deepEqual(out.counts, { missing: 1, changed: 0, malformed: 0 });
});

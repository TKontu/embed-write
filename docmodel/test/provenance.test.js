// SL-03: draft provenance per node through accept, reject, manual edits, split/merge and undo.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState } from 'prosemirror-state';
import { history, undo, redo } from 'prosemirror-history';
import * as api from '../src/index.js';

const {
  provenancePlugin, provenanceKey, provenanceOf, currentProvenance, provenanceChanges,
  parseMarkdown, assignIds, idPlugin, openMarkdown, buildSidecar, serializeSidecar, parseSidecar,
  reattachIds, serializeMarkdown, schema,
} = api;
const FIXTURE = '# Heading here\n\nHuman paragraph text.\n\nMachine one wrote this.\n\nMachine two wrote that.\n';
const RUN = 'run-01';

/** Paragraph blocks: [{id, pos, node}] in document order. */
const paras = (state) => {
  const out = [];
  state.doc.descendants((n, pos) => { if (n.type.name === 'paragraph') out.push({ id: n.attrs.id, pos, node: n }); });
  return out;
};
const mk = (plugins = [], seen = []) => {
  let state = EditorState.create({
    doc: assignIds(parseMarkdown(FIXTURE)),
    plugins: [provenancePlugin({ onChange: (c) => seen.push(...c) }), idPlugin(), ...plugins],
  });
  const [, m1, m2] = paras(state);
  state = state.apply(state.tr.setMeta(provenanceKey, { machine: { run: RUN, ids: [m1.id, m2.id] } }));
  return state;
};
const kind = (state, id) => provenanceOf(state, id).kind;

test('(a) machine insertion marks nodes machine with the run id; others are human', () => {
  const seen = [];
  const state = mk([], seen);
  const [h, m1, m2] = paras(state);
  assert.deepEqual(provenanceOf(state, m1.id), { kind: 'machine', run: RUN });
  assert.deepEqual(provenanceOf(state, m2.id), { kind: 'machine', run: RUN });
  assert.deepEqual(provenanceOf(state, h.id), { kind: 'human', run: null });
  assert.deepEqual(seen, [m1, m2].map((p) => ({ node: p.id, from: 'human', to: 'machine', run: RUN, cause: 'insert' })));
  assert.deepEqual(provenanceChanges(state), seen);
  assert.throws(() => state.apply(state.tr.setMeta(provenanceKey, { machine: { run: RUN, ids: ['nope'] } })), /provenance/);
  assert.throws(() => state.apply(state.tr.setMeta(provenanceKey, { machine: { run: '', ids: [m1.id] } })), /provenance/);
});

test('(b) accept keeps machine (and machine-edited) and emits one accept change', () => {
  let state = mk();
  const [h, m1, m2] = paras(state);
  state = state.apply(state.tr.setMeta(provenanceKey, { accept: [m1.id] }));
  assert.equal(kind(state, m1.id), 'machine');
  assert.deepEqual(provenanceChanges(state), [{ node: m1.id, from: 'machine', to: 'machine', run: RUN, cause: 'accept' }]);
  state = state.apply(state.tr.insertText('X', m2.pos + 1));
  state = state.apply(state.tr.setMeta(provenanceKey, { accept: [m2.id] }));
  assert.equal(kind(state, m2.id), 'machine-edited');
  assert.equal(provenanceChanges(state).length, 1);
  assert.throws(() => state.apply(state.tr.setMeta(provenanceKey, { accept: [h.id] })), /no machine entry/);
});

test('(c) reject removes the machine node and its entry with one reject change', () => {
  let state = mk();
  const [, m1, m2] = paras(state);
  state = state.apply(state.tr.delete(m1.pos, m1.pos + m1.node.nodeSize).setMeta(provenanceKey, { reject: [m1.id] }));
  assert.ok(!state.doc.textContent.includes('Machine one'));
  assert.deepEqual(provenanceChanges(state), [{ node: m1.id, from: 'machine', to: null, run: RUN, cause: 'reject' }]);
  assert.deepEqual(currentProvenance(state).map((e) => e.node), [m2.id]);
  // Reject by replacing the text with human text: node survives as human.
  const p = paras(state).find((x) => x.id === m2.id);
  state = state.apply(state.tr.insertText('Expert words.', p.pos + 1, p.pos + 1 + p.node.content.size)
    .setMeta(provenanceKey, { reject: [m2.id] }));
  assert.deepEqual(provenanceChanges(state), [{ node: m2.id, from: 'machine', to: 'human', run: RUN, cause: 'reject' }]);
  assert.deepEqual(provenanceOf(state, m2.id), { kind: 'human', run: null });
  assert.deepEqual(currentProvenance(state), []);
});

test('(d) manual edit turns machine into machine-edited once; human edits emit nothing', () => {
  const seen = [];
  let state = mk([], seen);
  seen.length = 0;
  const [h, m1] = paras(state);
  state = state.apply(state.tr.insertText('Q', m1.pos + 3));
  assert.deepEqual(provenanceOf(state, m1.id), { kind: 'machine-edited', run: RUN });
  assert.deepEqual(seen, [{ node: m1.id, from: 'machine', to: 'machine-edited', run: RUN, cause: 'edit' }]);
  state = state.apply(state.tr.insertText('R', m1.pos + 3));
  state = state.apply(state.tr.delete(m1.pos + 2, m1.pos + 4));
  state = state.apply(state.tr.insertText('H', h.pos + 2));
  assert.equal(seen.length, 1, 'no further changes');
  assert.equal(kind(state, m1.id), 'machine-edited');
  assert.equal(kind(state, h.id), 'human');
});

test('(e) split: second half gets a new id inheriting the kind; neither half is edited', () => {
  const seen = [];
  let state = mk([history()], seen);
  seen.length = 0;
  const [, m1] = paras(state);
  const dispatch = (tr) => { state = state.apply(tr); };
  dispatch(state.tr.split(m1.pos + 1 + 'Machine one'.length));
  const [, a, b] = paras(state);
  assert.equal(a.id, m1.id);
  assert.notEqual(b.id, m1.id);
  assert.deepEqual(provenanceOf(state, a.id), { kind: 'machine', run: RUN });
  assert.deepEqual(provenanceOf(state, b.id), { kind: 'machine', run: RUN });
  assert.deepEqual(seen, [{ node: b.id, from: 'human', to: 'machine', run: RUN, cause: 'insert' }]);
  // Undo merges back: the split-off id disappears, the original stays machine.
  assert.ok(undo(state, dispatch));
  assert.equal(paras(state).length, 3);
  assert.equal(kind(state, m1.id), 'machine');
  assert.equal(kind(state, b.id), 'human');
  assert.ok(redo(state, dispatch));
  assert.deepEqual(paras(state).slice(1, 3).map((p) => p.id), [m1.id, b.id]);
  assert.equal(kind(state, b.id), 'machine');
});

test('(e) merge: machine+machine of one run stays machine; human+machine is machine-edited', () => {
  let state = mk();
  const [h, m1, m2] = paras(state);
  state = state.apply(state.tr.join(m2.pos));
  assert.equal(paras(state).length, 2);
  assert.deepEqual(provenanceOf(state, m1.id), { kind: 'machine', run: RUN });
  assert.equal(kind(state, m2.id), 'human');
  assert.deepEqual(provenanceChanges(state), [{ node: m2.id, from: 'machine', to: null, run: RUN, cause: 'edit' }]);
  state = state.apply(state.tr.join(paras(state)[1].pos));
  assert.deepEqual(provenanceOf(state, h.id), { kind: 'machine-edited', run: RUN });
  assert.deepEqual(currentProvenance(state), [{ node: h.id, kind: 'machine-edited', run: RUN }]);
});

test('(e2) deleting an empty human paragraph next to a machine node leaves the machine node alone', () => {
  const seen = [];
  let state = mk([], seen);
  const [, , m2] = paras(state);
  const empty = schema.nodes.paragraph.create({ id: 'empty-human' });
  state = state.apply(state.tr.insert(m2.pos + m2.node.nodeSize, empty));
  const e = paras(state).find((p) => p.id === 'empty-human');
  seen.length = 0;
  state = state.apply(state.tr.delete(e.pos, e.pos + e.node.nodeSize));
  assert.deepEqual(provenanceChanges(state), []);
  assert.deepEqual(seen, []);
  assert.deepEqual(provenanceOf(state, m2.id), { kind: 'machine', run: RUN });
});

test('(e3) cross-block delete from a human node into a machine node makes the survivor machine-edited', () => {
  let state = mk();
  const [h, m1] = paras(state);
  state = state.apply(state.tr.delete(h.pos + 3, m1.pos + 3));
  assert.equal(paras(state).length, 2);
  assert.deepEqual(provenanceOf(state, h.id), { kind: 'machine-edited', run: RUN });
  assert.equal(kind(state, m1.id), 'human');
  assert.ok(provenanceChanges(state).some((c) => c.node === h.id && c.to === 'machine-edited' && c.cause === 'edit'));
});

test('(e) undo/redo of an edit keeps machine-edited; undo of a deletion restores the entry', () => {
  let state = mk([history()]);
  const dispatch = (tr) => { state = state.apply(tr); };
  const [, m1, m2] = paras(state);
  dispatch(state.tr.insertText('Q', m1.pos + 2));
  assert.equal(kind(state, m1.id), 'machine-edited');
  assert.ok(undo(state, dispatch));
  assert.ok(state.doc.textContent.includes('Machine one wrote this.'));
  assert.equal(kind(state, m1.id), 'machine-edited', 'undo does not un-edit');
  assert.ok(redo(state, dispatch));
  assert.equal(kind(state, m1.id), 'machine-edited');
  const p = paras(state).find((x) => x.id === m2.id);
  dispatch(state.tr.delete(p.pos, p.pos + p.node.nodeSize));
  assert.equal(kind(state, m2.id), 'human');
  assert.deepEqual(provenanceChanges(state), [{ node: m2.id, from: 'machine', to: null, run: RUN, cause: 'edit' }]);
  assert.ok(undo(state, dispatch));
  assert.deepEqual(provenanceOf(state, m2.id), { kind: 'machine', run: RUN });
  assert.deepEqual(provenanceChanges(state), [{ node: m2.id, from: 'human', to: 'machine', run: RUN, cause: 'insert' }]);
  assert.ok(redo(state, dispatch));
  assert.equal(kind(state, m2.id), 'human');
});

test('(f) currentProvenance -> sidecar -> reopen gives the same provenance', () => {
  let state = mk();
  const [, m1] = paras(state);
  state = state.apply(state.tr.insertText('Q', m1.pos + 2));
  const entries = currentProvenance(state);
  assert.equal(entries.length, 2);
  assert.deepEqual(entries.map((e) => Object.keys(e)), entries.map(() => ['node', 'kind', 'run']));
  const sidecar = parseSidecar(serializeSidecar({ ...buildSidecar(state.doc), provenance: entries }));
  const opened = openMarkdown(serializeMarkdown(state.doc));
  assert.equal(opened.readOnly, false);
  const { doc } = reattachIds(opened.doc, sidecar);
  let fresh = EditorState.create({ doc, plugins: [provenancePlugin(), idPlugin()] });
  fresh = fresh.apply(fresh.tr.setMeta(provenanceKey, { restore: sidecar.provenance }));
  assert.deepEqual(currentProvenance(fresh), entries);
  assert.deepEqual(provenanceChanges(fresh), [], 'restore emits no transitions');
  for (const p of paras(state)) assert.deepEqual(provenanceOf(fresh, p.id), provenanceOf(state, p.id));
});

test('no-op transactions keep the plugin state and report no changes', () => {
  const state = mk();
  const next = state.apply(state.tr.setMeta('other', 1));
  assert.deepEqual(provenanceChanges(next), []);
  assert.deepEqual(currentProvenance(next), currentProvenance(state));
  assert.ok(schema.nodes.paragraph);
});

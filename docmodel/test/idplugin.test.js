import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState, Plugin } from 'prosemirror-state';
import { history, undo, redo } from 'prosemirror-history';
import * as model from '../src/index.js';

const opts = { now: () => 123456789, rand: (buf) => buf.fill(0) };
const ids = (doc) => {
  const result = [];
  doc.descendants((node) => {
    if (node.type.spec.attrs && 'id' in node.type.spec.attrs) result.push(node.attrs.id);
  });
  return result;
};
const valid = (doc) => {
  const values = ids(doc);
  assert.ok(values.every((id) => typeof id === 'string' && id.length > 0));
  assert.equal(new Set(values).size, values.length);
};
const stateFor = (text) => EditorState.create({
  doc: model.assignIds(model.parseMarkdown(text)),
  // A no-op baseline lets RED demonstrate the missing behavior before the export exists.
  plugins: [model.idPlugin ? model.idPlugin(opts) : new Plugin({}), history()],
});
function roundTrip(original, tr, check) {
  let state = original.applyTransaction(tr).state;
  valid(state.doc);
  check(state.doc);
  const edited = state.doc;
  const dispatch = (transaction) => { state = state.applyTransaction(transaction).state; valid(state.doc); };
  assert.ok(undo(state, dispatch));
  assert.deepEqual(state.doc.toJSON(), original.doc.toJSON());
  assert.deepEqual(ids(state.doc), ids(original.doc));
  assert.ok(redo(state, dispatch));
  assert.deepEqual(state.doc.toJSON(), edited.toJSON());
}

test('paragraph split keeps the first id, repairs the second, and survives undo/redo', () => {
  const state = stateFor('alpha beta\n\nlast');
  roundTrip(state, state.tr.split(6), (doc) => {
    assert.equal(doc.child(0).attrs.id, state.doc.child(0).attrs.id);
    assert.notEqual(doc.child(1).attrs.id, state.doc.child(0).attrs.id);
  });
});

test('list item split repairs both item and paragraph ids, including undo/redo', () => {
  const state = stateFor('- alpha beta\n- last');
  roundTrip(state, state.tr.split(8, 2), (doc) => {
    const before = state.doc.firstChild.firstChild;
    const list = doc.firstChild;
    assert.equal(list.child(0).attrs.id, before.attrs.id);
    assert.equal(list.child(0).firstChild.attrs.id, before.firstChild.attrs.id);
    assert.notEqual(list.child(1).attrs.id, before.attrs.id);
    assert.notEqual(list.child(1).firstChild.attrs.id, before.firstChild.attrs.id);
  });
});

test('joining paragraphs keeps the first id, including undo/redo', () => {
  const state = stateFor('first\n\nsecond');
  roundTrip(state, state.tr.join(state.doc.firstChild.nodeSize), (doc) => {
    assert.equal(doc.childCount, 1);
    assert.equal(doc.firstChild.attrs.id, state.doc.firstChild.attrs.id);
    assert.ok(!ids(doc).includes(state.doc.child(1).attrs.id));
  });
});

test('moving a nested blockquote preserves every descendant id, including undo/redo', () => {
  const state = stateFor('> first\n>\n> > nested\n> >\n> > paragraph\n\nafter');
  const size = state.doc.firstChild.nodeSize;
  const slice = state.doc.slice(0, size);
  const tr = state.tr.delete(0, size);
  tr.replace(tr.doc.content.size, tr.doc.content.size, slice);
  roundTrip(state, tr, (doc) => {
    assert.deepEqual(doc.lastChild.toJSON(), state.doc.firstChild.toJSON());
    assert.deepEqual(ids(doc).sort(), ids(state.doc).sort());
  });
});

test('pasting a duplicate repairs the later copy, including undo/redo', () => {
  const state = stateFor('original');
  roundTrip(state, state.tr.insert(state.doc.content.size, state.doc.firstChild), (doc) => {
    assert.equal(doc.firstChild.attrs.id, state.doc.firstChild.attrs.id);
    assert.notEqual(doc.lastChild.attrs.id, doc.firstChild.attrs.id);
    assert.match(doc.lastChild.attrs.id, /^00003NQK8N[0-9A-HJKMNP-TV-Z]{16}$/);
  });
});

test('fixIds repairs null ids on structural blocks with attribute-only steps', () => {
  const doc = model.parseMarkdown('- item\n\n| a | b |\n|---|---|\n| c | d |');
  const before = doc.toJSON();
  const tr = EditorState.create({ doc }).tr;
  assert.equal(typeof model.fixIds, 'function');
  assert.equal(model.fixIds(doc, tr), ids(doc).length);
  valid(tr.doc);
  assert.ok(tr.steps.every((step) => step.toJSON().stepType === 'attr'));
  assert.deepEqual(doc.toJSON(), before);
  assert.equal(model.fixIds(tr.doc, tr), 0);
});

test('valid text edits and empty transactions append no transaction', () => {
  const state = stateFor('hello');
  assert.equal(typeof model.idPlugin, 'function');
  assert.equal(state.applyTransaction(state.tr).transactions.length, 1);
  const result = state.applyTransaction(state.tr.insertText('!', 3));
  assert.equal(result.transactions.length, 1);
  valid(result.state.doc);
  assert.deepEqual(ids(result.state.doc), ids(state.doc));
  assert.equal(model.idPlugin().spec.appendTransaction([], state, state), null);
});

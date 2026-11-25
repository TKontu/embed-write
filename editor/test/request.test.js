// UX-03: proposals on request only. Mod-Shift-p asks for a proposal for the selection; typing and
// selection changes never do, and nothing is rendered outside the editor's content (no ghost text).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, proposalRequestKeymap } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');

const mount = () => document.body.appendChild(document.createElement('div'));
const MD = 'The cat sat on the mat.\n';

function find(ed, s) {
  let r = null;
  ed.view.state.doc.descendants((n, pos) => {
    if (r || !n.isText) return !r;
    const i = n.text.indexOf(s);
    if (i >= 0) r = { from: pos + i, to: pos + i + s.length };
    return false;
  });
  assert.ok(r, s);
  return r;
}
const select = (ed, from, to) =>
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, from, to)));
/** Fire Mod-Shift-p through the view's keydown handlers; Mod is Ctrl off Mac (jsdom). */
function pressRequest(ed) {
  const ev = new window.KeyboardEvent('keydown', { key: 'P', code: 'KeyP', keyCode: 80, ctrlKey: true, metaKey: false, shiftKey: true, bubbles: true, cancelable: true });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}
/** Everything in the document body except the editor's own contenteditable subtree. */
const outside = (root, ed) => [...root.querySelectorAll('*')].filter((el) => !ed.view.dom.contains(el) && el !== ed.view.dom && !el.contains(ed.view.dom)).length;

test('Mod-Shift-p with a selection calls onRequest once with range and text; doc unchanged', async () => {
  const calls = [];
  const ed = await createEditor({ root: mount(), markdown: MD, onRequest: (r) => calls.push(r) });
  try {
    const md0 = ed.getMarkdown();
    const { from, to } = find(ed, 'cat sat');
    select(ed, from, to);
    assert.equal(pressRequest(ed), true);
    assert.deepEqual(calls, [{ from, to, text: 'cat sat' }]);
    assert.equal(ed.getMarkdown(), md0);
  } finally { await ed.destroy(); }
});

test('Mod-Shift-p with an empty selection does not call onRequest', async () => {
  const calls = [];
  const ed = await createEditor({ root: mount(), markdown: MD, onRequest: (r) => calls.push(r) });
  try {
    const { from } = find(ed, 'cat');
    select(ed, from, from);
    assert.equal(pressRequest(ed), false);
    assert.equal(calls.length, 0);
  } finally { await ed.destroy(); }
});

test('typing and selection changes never request and add no ghost DOM', async () => {
  const calls = [];
  const root = mount();
  const ed = await createEditor({ root, markdown: MD, onRequest: (r) => calls.push(r) });
  try {
    const before = outside(root, ed);
    const { from, to } = find(ed, 'mat');
    select(ed, from, to);
    select(ed, from, from);
    ed.view.dispatch(ed.view.state.tr.insertText('big ', from));
    select(ed, 1, 5);
    ed.view.dispatch(ed.view.state.tr.insertText('X'));
    assert.equal(calls.length, 0);
    assert.equal(outside(root, ed), before);
    assert.equal(root.querySelectorAll('.proposal, [data-proposal]').length, 0);
    assert.match(ed.getMarkdown(), /big mat/);
  } finally { await ed.destroy(); }
});

test('editor without onRequest is unchanged: Mod-Shift-p is not handled, doc unchanged', async () => {
  const ed = await createEditor({ root: mount(), markdown: MD });
  try {
    const md0 = ed.getMarkdown();
    const { from, to } = find(ed, 'cat');
    select(ed, from, to);
    assert.equal(pressRequest(ed), false);
    assert.equal(ed.getMarkdown(), md0);
  } finally { await ed.destroy(); }
});

test('proposalRequestKeymap is exported as a plugin factory', () => {
  assert.equal(typeof proposalRequestKeymap, 'function');
  assert.ok(proposalRequestKeymap({ onRequest() {} }).props.handleKeyDown);
});

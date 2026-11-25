// UX-02: showProposal panel — diff visible before action; accept / edit / reject (Escape) once.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, showProposal, undo } = await import('../src/index.js');

const MD = '# Title\n\nThe cat sat on the mat.\n';
const mount = () => document.body.appendChild(document.createElement('div'));
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
// Rows as service/word_diff.py would emit for 'cat' -> 'dog'.
const ops = [{ kind: 'replace', original_text: 'cat', candidate_text: 'dog' }];

async function setup() {
  const ed = await createEditor({ root: mount(), markdown: MD });
  const calls = [];
  const panel = showProposal(ed, { ...find(ed, 'cat'), original: 'cat', text: 'dog', ops },
    { onAction: (a) => calls.push(a) });
  document.body.appendChild(panel);
  const q = (s) => panel.querySelector(s);
  return { ed, calls, panel, q, accept: q('button[data-action="accept"]'),
    reject: q('button[data-action="reject"]'), field: q('textarea') };
}
const key = (el, init) => el.dispatchEvent(new window.KeyboardEvent('keydown', { bubbles: true, ...init }));

test('diff is rendered in the panel before any action', async () => {
  const { ed, panel, q, field, calls } = await setup();
  try {
    assert.equal(q('del').textContent, 'cat');
    assert.equal(q('ins').textContent, 'dog');
    assert.equal(field.value, 'dog');
    assert.equal(ed.getMarkdown(), MD);
    assert.equal(calls.length, 0);
    assert.ok(panel.isConnected);
  } finally { await ed.destroy(); }
});

test('Accept applies the candidate and reports accept', async () => {
  const { ed, accept, calls } = await setup();
  try {
    const r = find(ed, 'cat');
    accept.click();
    assert.equal(ed.getMarkdown(), MD.replace('cat', 'dog'));
    assert.deepEqual(calls, [{ action: 'accept', original: 'cat', candidate: 'dog', final: 'dog', ...r }]);
  } finally { await ed.destroy(); }
});

test('edit then Accept applies the edited text and reports edit', async () => {
  const { ed, accept, field, calls } = await setup();
  try {
    field.value = 'bird';
    accept.click();
    assert.equal(ed.getMarkdown(), MD.replace('cat', 'bird'));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].action, 'edit');
    assert.equal(calls[0].candidate, 'dog');
    assert.equal(calls[0].final, 'bird');
  } finally { await ed.destroy(); }
});

test('Reject button leaves the document unchanged', async () => {
  const { ed, reject, calls } = await setup();
  try {
    reject.click();
    assert.equal(ed.getMarkdown(), MD);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].action, 'reject');
    assert.equal(calls[0].final, null);
  } finally { await ed.destroy(); }
});

test('a single Escape inside the panel rejects', async () => {
  const { ed, field, calls } = await setup();
  try {
    key(field, { key: 'Escape' });
    assert.equal(ed.getMarkdown(), MD);
    assert.deepEqual(calls.map((c) => c.action), ['reject']);
  } finally { await ed.destroy(); }
});

test('Ctrl+Enter accepts', async () => {
  const { ed, field, calls } = await setup();
  try {
    key(field, { key: 'Enter', ctrlKey: true });
    assert.equal(ed.getMarkdown(), MD.replace('cat', 'dog'));
    assert.deepEqual(calls.map((c) => c.action), ['accept']);
  } finally { await ed.destroy(); }
});

test('a second action after the first does nothing', async () => {
  const { ed, accept, reject, field, calls, panel } = await setup();
  try {
    accept.click();
    accept.click();
    reject.click();
    key(field, { key: 'Escape' });
    assert.equal(calls.length, 1);
    assert.equal(ed.getMarkdown(), MD.replace('cat', 'dog'));
    assert.equal(panel.isConnected, false);
  } finally { await ed.destroy(); }
});

test('accept then undo restores the original markdown exactly', async () => {
  const { ed, accept } = await setup();
  try {
    accept.click();
    assert.equal(undo(ed), true);
    assert.equal(ed.getMarkdown(), MD);
  } finally { await ed.destroy(); }
});

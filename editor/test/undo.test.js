// UX-04: acceptProposal is one undoable transaction; undo restores the document exactly.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, acceptProposal, undo } = await import('../src/index.js');
const { hashText } = await import('docmodel');

const mount = () => document.body.appendChild(document.createElement('div'));
const h = (ed) => hashText(ed.getMarkdown());
// Block ids are assigned by idPlugin to id-less blocks after any transaction (undo included), so
// structure is compared without them; the serialized-document hash is the exactness check.
const shape = (ed) => JSON.parse(JSON.stringify(ed.view.state.doc.toJSON(), (k, v) => (k === 'id' ? undefined : v)));
/** Position range of the first occurrence of `s` in a text node. */
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

test('accept then undo restores hash exactly', async () => {
  const ed = await createEditor({ root: mount(), markdown: '# Title\n\nThe cat sat on the mat.\n' });
  try {
    const h0 = h(ed);
    const json0 = shape(ed);
    assert.equal(acceptProposal(ed, { ...find(ed, 'cat'), text: 'dog' }), true);
    assert.match(ed.getMarkdown(), /The dog sat/);
    assert.notEqual(h(ed), h0);
    assert.equal(undo(ed), true);
    assert.equal(h(ed), h0);
    assert.deepEqual(shape(ed), json0);
  } finally { await ed.destroy(); }
});

test('two accepts, two undos: each undo reverts one accept', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'alpha beta gamma\n\ndelta epsilon\n' });
  try {
    const h0 = h(ed);
    acceptProposal(ed, { ...find(ed, 'beta'), text: 'BETA' });
    const h1 = h(ed);
    acceptProposal(ed, { ...find(ed, 'epsilon'), text: 'EPS' });
    assert.notEqual(h(ed), h1);
    undo(ed);
    assert.equal(h(ed), h1);
    undo(ed);
    assert.equal(h(ed), h0);
    assert.equal(undo(ed), false);
  } finally { await ed.destroy(); }
});

test('replaced range spanning marks is restored exactly', async () => {
  const src = 'plain **bold _both_ text** and `code` end\n';
  const ed = await createEditor({ root: mount(), markdown: src });
  try {
    const h0 = h(ed);
    const json0 = shape(ed);
    const range = { from: find(ed, 'plain').from + 2, to: find(ed, 'code').to - 1 };
    acceptProposal(ed, { ...range, text: 'X' });
    assert.notEqual(h(ed), h0);
    undo(ed);
    assert.equal(h(ed), h0);
    assert.deepEqual(shape(ed), json0);
  } finally { await ed.destroy(); }
});

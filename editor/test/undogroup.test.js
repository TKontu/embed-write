// BH-07: typing runs coalesce into one undo step; each formatting command is its own step.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, undo } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');

const mount = () => document.body.appendChild(document.createElement('div'));

/** Three insertText transactions at the end of the first paragraph, back to back. */
function typeAbc(ed) {
  for (const ch of 'abc') {
    const { state } = ed.view;
    ed.view.dispatch(state.tr.insertText(ch, state.selection.from));
  }
}
const atEndOfFirst = (ed) => {
  const end = ed.view.state.doc.firstChild.nodeSize - 1;
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, end)));
};
const selectAbc = (ed) => {
  const end = ed.view.state.doc.firstChild.nodeSize - 1;
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, end - 3, end)));
};
function press(ed, key, code = `Key${key.toUpperCase()}`) {
  const ev = new window.KeyboardEvent('keydown', { key, code, keyCode: key.toUpperCase().charCodeAt(0), ctrlKey: true, bubbles: true, cancelable: true });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}
const open = () => createEditor({ root: mount(), markdown: 'x\n' });

test('three typed characters undo as one step', async () => {
  const ed = await open();
  try {
    atEndOfFirst(ed);
    typeAbc(ed);
    assert.equal(ed.getMarkdown(), 'xabc\n');
    assert.equal(undo(ed), true);
    assert.equal(ed.getMarkdown(), 'x\n');
  } finally { await ed.destroy(); }
});

for (const [key, want] of [['b', 'x**abc**\n'], ['i', 'x*abc*\n'], ['e', 'x`abc`\n'], ['2', '## xabc\n']]) {
  test(`Mod-${key} right after typing is its own undo step`, async () => {
    const ed = await open();
    try {
      atEndOfFirst(ed);
      typeAbc(ed);
      selectAbc(ed);
      assert.equal(press(ed, key, /\d/.test(key) ? `Digit${key}` : undefined), true);
      assert.equal(ed.getMarkdown(), want);
      assert.equal(undo(ed), true);
      assert.equal(ed.getMarkdown(), 'xabc\n');
      assert.equal(undo(ed), true);
      assert.equal(ed.getMarkdown(), 'x\n');
    } finally { await ed.destroy(); }
  });
}

test('two formatting commands in a row are two undo steps', async () => {
  const ed = await open();
  try {
    atEndOfFirst(ed);
    typeAbc(ed);
    selectAbc(ed);
    press(ed, 'b');
    press(ed, 'i');
    assert.match(ed.getMarkdown(), /\*\*\*abc\*\*\*|\*\*_abc_\*\*|_\*\*abc\*\*_|\*\*\*abc\*\*\*/);
    undo(ed);
    assert.equal(ed.getMarkdown(), 'x**abc**\n');
    undo(ed);
    assert.equal(ed.getMarkdown(), 'xabc\n');
  } finally { await ed.destroy(); }
});

// FM-02: Mod-1..6 set/toggle heading level; `#`..`######` + space at paragraph start makes a heading.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');

const mount = () => document.body.appendChild(document.createElement('div'));
const caret = (ed, pos) =>
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, pos)));
/** Fire Mod-<digit> through the view's keydown handlers; Mod is Ctrl off Mac (jsdom). */
function press(ed, n) {
  const ev = new window.KeyboardEvent('keydown', { key: String(n), code: `Digit${n}`, keyCode: 48 + n, ctrlKey: true, bubbles: true, cancelable: true });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}
/** Type text at the caret as the browser would: handleTextInput first, else insertText. */
function type(ed, text) {
  for (const ch of text) {
    const { from, to } = ed.view.state.selection;
    const handled = ed.view.someProp('handleTextInput', (f) => f(ed.view, from, to, ch));
    if (!handled) ed.view.dispatch(ed.view.state.tr.insertText(ch, from, to));
  }
}

for (let n = 1; n <= 6; n++) {
  test(`Mod-${n} makes a paragraph a level-${n} heading and back`, async () => {
    const ed = await createEditor({ root: mount(), markdown: 'Title\n' });
    try {
      caret(ed, 2);
      assert.equal(press(ed, n), true);
      assert.equal(ed.getMarkdown(), `${'#'.repeat(n)} Title\n`);
      assert.equal(press(ed, n), true);
      assert.equal(ed.getMarkdown(), 'Title\n');
    } finally { await ed.destroy(); }
  });
}

test('Mod-N changes an existing heading level', async () => {
  const ed = await createEditor({ root: mount(), markdown: '# Title\n' });
  try {
    caret(ed, 2);
    assert.equal(press(ed, 3), true);
    assert.equal(ed.getMarkdown(), '### Title\n');
  } finally { await ed.destroy(); }
});

test('Mod-N applies to every textblock in the selection', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'a\n\nb\n' });
  try {
    const { doc } = ed.view.state;
    ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(doc, 1, doc.content.size - 1)));
    assert.equal(press(ed, 2), true);
    assert.equal(ed.getMarkdown(), '## a\n\n## b\n');
  } finally { await ed.destroy(); }
});

test('"## " typed at paragraph start makes a level-2 heading', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'Title\n' });
  try {
    caret(ed, 1);
    type(ed, '## ');
    assert.equal(ed.view.state.doc.firstChild.type.name, 'heading');
    assert.equal(ed.view.state.doc.firstChild.attrs.level, 2);
    assert.equal(ed.getMarkdown(), '## Title\n');
  } finally { await ed.destroy(); }
});

test('"###### " converts to level 6; seven hashes do not convert', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'x\n' });
  try {
    caret(ed, 1);
    type(ed, '###### ');
    assert.equal(ed.getMarkdown(), '###### x\n');
  } finally { await ed.destroy(); }
  const ed2 = await createEditor({ root: mount(), markdown: 'x\n' });
  try {
    caret(ed2, 1);
    type(ed2, '####### ');
    assert.equal(ed2.view.state.doc.firstChild.type.name, 'paragraph');
  } finally { await ed2.destroy(); }
});

test('"# " mid-paragraph is not converted', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'ab\n' });
  try {
    caret(ed, 2);
    type(ed, '# ');
    assert.equal(ed.view.state.doc.firstChild.type.name, 'paragraph');
    assert.equal(ed.view.state.doc.firstChild.textContent, 'a# b');
  } finally { await ed.destroy(); }
});

test('heading shortcuts and input rule do not act in source view', async () => {
  const ed = await createEditor({ root: mount(), markdown: '##Title\n' });
  try {
    const md0 = ed.getMarkdown();
    caret(ed, 3);
    ed.showSource();
    assert.equal(press(ed, 2), false);
    const handled = ed.view.someProp('handleTextInput', (f) => f(ed.view, 3, 3, ' '));
    assert.ok(!handled);
    ed.showRich();
    assert.equal(ed.view.state.doc.firstChild.type.name, 'paragraph');
    assert.equal(ed.getMarkdown(), md0);
  } finally { await ed.destroy(); }
});

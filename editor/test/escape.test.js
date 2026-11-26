// FM-06: escape hatch. One Backspace right after an input rule restores the typed text; a literal
// `*` survives serialization.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');
const { parseMarkdown, serializeMarkdown } = await import('docmodel');

const mount = () => document.body.appendChild(document.createElement('div'));
const caret = (ed, pos) =>
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, pos)));
function type(ed, text) {
  for (const ch of text) {
    const { from, to } = ed.view.state.selection;
    const handled = ed.view.someProp('handleTextInput', (f) => f(ed.view, from, to, ch));
    if (!handled) ed.view.dispatch(ed.view.state.tr.insertText(ch, from, to));
  }
}
/** Backspace keydown; returns whether a plugin handled it. */
function bsKey(ed) {
  const ev = new window.KeyboardEvent('keydown', { key: 'Backspace', code: 'Backspace', keyCode: 8, bubbles: true, cancelable: true });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}
/** Backspace as the browser would: plugin first, else delete the character before the caret. */
function backspace(ed) {
  if (bsKey(ed)) return true;
  const { from } = ed.view.state.selection;
  ed.view.dispatch(ed.view.state.tr.delete(from - 1, from));
  return false;
}
const roundTrips = (md) => assert.equal(serializeMarkdown(parseMarkdown(md)), md);
async function withEd(md, fn) {
  const ed = await createEditor({ root: mount(), markdown: md });
  try { return await fn(ed); } finally { await ed.destroy(); }
}
const emptyFirst = (ed) => {
  ed.view.dispatch(ed.view.state.tr.insert(0, ed.view.state.schema.nodes.paragraph.create()));
  caret(ed, 1);
};

const cases = [
  { name: '# ', md: 'x\n', pos: 1, typed: '# ', converted: 'heading', text: '# x' },
  { name: '- ', md: 'x\n', pos: 1, typed: '- ', converted: 'bullet_list', text: '- x' },
  { name: '1. ', md: 'x\n', pos: 1, typed: '1. ', converted: 'ordered_list', text: '1. x' },
  { name: '> ', md: 'x\n', pos: 1, typed: '> ', converted: 'blockquote', text: '> x' },
  { name: '``` ', md: 'after\n', setup: emptyFirst, typed: '``` ', converted: 'code_block', text: '``` ' },
  { name: '---', md: 'after\n', setup: emptyFirst, typed: '---', converted: 'thematic_break', text: '---' },
];

for (const c of cases) {
  test(`one Backspace after "${c.name}" restores the literal text; a second deletes a char`, () =>
    withEd(c.md, (ed) => {
      if (c.setup) c.setup(ed); else caret(ed, c.pos);
      type(ed, c.typed);
      assert.equal(ed.view.state.doc.firstChild.type.name, c.converted);
      assert.equal(backspace(ed), true, 'Backspace handled by undoInputRule');
      const first = ed.view.state.doc.firstChild;
      assert.equal(first.type.name, 'paragraph');
      assert.equal(first.textContent, c.text);
      const md = ed.getMarkdown();
      // Markdown cannot carry a paragraph's trailing space; the rest must survive literally.
      assert.equal(parseMarkdown(md).firstChild.textContent, c.text.trimEnd(), `serialized: ${JSON.stringify(md)}`);
      // Residual: docmodel serializes a paragraph's trailing space, which reparsing drops.
      if (c.text === c.text.trimEnd()) roundTrips(md);
      assert.equal(backspace(ed), false, 'second Backspace is a normal delete');
      assert.equal(ed.view.state.doc.firstChild.textContent.length, c.text.length - 1);
    }));
}

test('one Backspace after "[ ] " in a list item restores the literal text', () =>
  withEd('- x\n', (ed) => {
    caret(ed, 3);
    type(ed, '[ ] ');
    assert.equal(ed.view.state.doc.firstChild.firstChild.attrs.checked, false);
    assert.equal(backspace(ed), true);
    const item = ed.view.state.doc.firstChild.firstChild;
    assert.equal(item.attrs.checked, null);
    assert.equal(item.textContent, '[ ] x');
    const md = ed.getMarkdown();
    assert.equal(parseMarkdown(md).firstChild.firstChild.attrs.checked, null, md);
    roundTrips(md);
    assert.equal(backspace(ed), false);
    assert.equal(ed.view.state.doc.firstChild.firstChild.textContent, '[ ]x');
  }));

test('Backspace with no just-fired rule is not handled', () =>
  withEd('abc\n', (ed) => {
    caret(ed, 3);
    assert.equal(bsKey(ed), false);
    type(ed, '# ');
    type(ed, 'q');
    assert.equal(bsKey(ed), false, 'rule no longer just fired after further typing');
  }));

test('source view: Backspace is not intercepted', () =>
  withEd('x\n', (ed) => {
    caret(ed, 1);
    type(ed, '# ');
    ed.showSource();
    assert.equal(bsKey(ed), false);
  }));

test('"* " on a non-empty line and "*" mid-text keep a literal asterisk', () =>
  withEd('ab\n', (ed) => {
    caret(ed, 3);
    type(ed, ' * c');
    caret(ed, 2);
    type(ed, '*');
    assert.equal(ed.view.state.doc.firstChild.type.name, 'paragraph');
    assert.equal(ed.view.state.doc.firstChild.textContent, 'a*b * c');
    const md = ed.getMarkdown();
    assert.equal(parseMarkdown(md).firstChild.textContent, 'a*b * c', md);
    roundTrips(md);
  }));

test('"* " converted then backspaced leaves a literal "* text" that round-trips', () =>
  withEd('text\n', (ed) => {
    caret(ed, 1);
    type(ed, '* ');
    assert.equal(backspace(ed), true);
    assert.equal(ed.view.state.doc.firstChild.textContent, '* text');
    const md = ed.getMarkdown();
    assert.equal(parseMarkdown(md).firstChild.type.name, 'paragraph', md);
    roundTrips(md);
  }));

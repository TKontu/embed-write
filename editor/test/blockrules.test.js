// FM-03: block input rules for lists, task items, quotes, code fences and thematic breaks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');

const mount = () => document.body.appendChild(document.createElement('div'));
const caret = (ed, pos) =>
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, pos)));
/** Type text at the caret as the browser would: handleTextInput first, else insertText. */
function type(ed, text) {
  for (const ch of text) {
    const { from, to } = ed.view.state.selection;
    const handled = ed.view.someProp('handleTextInput', (f) => f(ed.view, from, to, ch));
    if (!handled) ed.view.dispatch(ed.view.state.tr.insertText(ch, from, to));
  }
}
function enter(ed) {
  const ev = new window.KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true, cancelable: true });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}
/** Open an editor on `md`, put the caret at `pos`, run `fn`, return the Markdown. */
async function run(md, pos, fn) {
  const ed = await createEditor({ root: mount(), markdown: md });
  try { caret(ed, pos); fn(ed); return { md: ed.getMarkdown(), doc: ed.view.state.doc }; }
  finally { await ed.destroy(); }
}

for (const m of ['-', '*', '+']) {
  test(`"${m} " at paragraph start makes a bullet list with marker ${m}`, async () => {
    const r = await run('item\n', 1, (ed) => type(ed, `${m} `));
    assert.equal(r.doc.firstChild.type.name, 'bullet_list');
    assert.equal(r.doc.firstChild.attrs.marker, m);
    assert.equal(r.md, `${m} item\n`);
  });
}

test('"3. " makes an ordered list starting at 3', async () => {
  const r = await run('item\n', 1, (ed) => type(ed, '3. '));
  assert.equal(r.doc.firstChild.type.name, 'ordered_list');
  assert.equal(r.doc.firstChild.attrs.start, 3);
  assert.equal(r.md, '3. item\n');
});

test('"1. " makes an ordered list starting at 1', async () => {
  const r = await run('item\n', 1, (ed) => type(ed, '1. '));
  assert.equal(r.md, '1. item\n');
});

test('"- [ ] " at paragraph start makes an unchecked task item', async () => {
  const r = await run('todo\n', 1, (ed) => type(ed, '- [ ] '));
  assert.equal(r.doc.firstChild.firstChild.attrs.checked, false);
  assert.equal(r.md, '- [ ] todo\n');
});

test('"[x] " at list item start makes a checked task item', async () => {
  const r = await run('- done\n', 3, (ed) => type(ed, '[x] '));
  assert.equal(r.doc.firstChild.firstChild.attrs.checked, true);
  assert.equal(r.md, '- [x] done\n');
});

test('"[ ] " outside a list item is plain text', async () => {
  const r = await run('a\n', 1, (ed) => type(ed, '[ ] '));
  assert.equal(r.doc.firstChild.type.name, 'paragraph');
  assert.equal(r.doc.firstChild.textContent, '[ ] a');
});

test('"> " makes a blockquote', async () => {
  const r = await run('quote\n', 1, (ed) => type(ed, '> '));
  assert.equal(r.doc.firstChild.type.name, 'blockquote');
  assert.equal(r.md, '> quote\n');
});

test('"```js " makes a code block with language js', async () => {
  const r = await run('after\n', 1, (ed) => {
    ed.view.dispatch(ed.view.state.tr.insert(0, ed.view.state.schema.nodes.paragraph.create()));
    caret(ed, 1); type(ed, '```js '); type(ed, 'x');
  });
  assert.equal(r.doc.firstChild.type.name, 'code_block');
  assert.equal(r.doc.firstChild.attrs.lang, 'js');
  assert.equal(r.md, '```js\nx\n```\n\nafter\n');
});

test('"```py" then Enter makes a code block with language py', async () => {
  const r = await run('after\n', 1, (ed) => {
    ed.view.dispatch(ed.view.state.tr.insert(0, ed.view.state.schema.nodes.paragraph.create()));
    caret(ed, 1); type(ed, '```py');
    assert.equal(enter(ed), true);
    type(ed, 'y');
  });
  assert.equal(r.doc.firstChild.type.name, 'code_block');
  assert.equal(r.doc.firstChild.attrs.lang, 'py');
  assert.equal(r.md, '```py\ny\n```\n\nafter\n');
});

test('"``` " without language makes a plain code block', async () => {
  const r = await run('after\n', 1, (ed) => {
    ed.view.dispatch(ed.view.state.tr.insert(0, ed.view.state.schema.nodes.paragraph.create()));
    caret(ed, 1); type(ed, '``` '); type(ed, 'z');
  });
  assert.equal(r.doc.firstChild.type.name, 'code_block');
  assert.equal(r.doc.firstChild.attrs.lang, null);
  assert.equal(r.md, '```\nz\n```\n\nafter\n');
});

for (const s of ['---', '***', '___']) {
  test(`"${s}" on an empty paragraph makes a thematic break with a ${s} marker`, async () => {
    const r = await run('after\n', 1, (ed) => {
      ed.view.dispatch(ed.view.state.tr.insert(0, ed.view.state.schema.nodes.paragraph.create()));
      caret(ed, 1); type(ed, s);
      const { $from } = ed.view.state.selection;
      assert.equal($from.parent.type.name, 'paragraph');
      assert.equal($from.parent.content.size, 0);
      type(ed, 'next');
    });
    assert.equal(r.doc.firstChild.type.name, 'thematic_break');
    assert.equal(r.doc.firstChild.attrs.marker, s);
    assert.equal(r.md, `${s}\n\nnext\n\nafter\n`);
  });
}

test('"---" before existing text does not make a rule', async () => {
  const r = await run('text\n', 1, (ed) => type(ed, '---'));
  assert.equal(r.doc.firstChild.type.name, 'paragraph');
  assert.equal(r.doc.firstChild.textContent, '---text');
});

test('block rules are not triggered mid-paragraph', async () => {
  for (const s of ['- ', '2. ', '> ', '```js ', '---']) {
    const r = await run('ab\n', 2, (ed) => type(ed, s));
    assert.equal(r.doc.firstChild.type.name, 'paragraph', s);
    assert.equal(r.doc.firstChild.textContent, `a${s}b`, s);
  }
});

test('block rules do not act in source view', async () => {
  const ed = await createEditor({ root: mount(), markdown: '-x\n' });
  try {
    const md0 = ed.getMarkdown();
    caret(ed, 2);
    ed.showSource();
    assert.ok(!ed.view.someProp('handleTextInput', (f) => f(ed.view, 2, 2, ' ')));
    ed.showRich();
    assert.equal(ed.view.state.doc.firstChild.type.name, 'paragraph');
    assert.equal(ed.getMarkdown(), md0);
  } finally { await ed.destroy(); }
});

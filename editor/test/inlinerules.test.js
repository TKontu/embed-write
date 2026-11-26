// FM-04: inline input rules. Typing the closing delimiter converts the just-typed span live.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');
const { parseMarkdown, serializeMarkdown, schema } = await import('docmodel');

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
async function withEd(md, fn) {
  const ed = await createEditor({ root: mount(), markdown: md });
  try { return await fn(ed); } finally { await ed.destroy(); }
}
/** [text, mark names] per inline child of the first block. */
const runs = (ed) => {
  const out = [];
  ed.view.state.doc.firstChild.forEach((n) => out.push([n.text, n.marks.map((m) => m.type.name)]));
  return out;
};
const roundTrips = (md) => assert.equal(serializeMarkdown(parseMarkdown(md)), md);

const cases = [
  { typed: '*hi there*', mark: 'em', md: 'a *hi there*\n' },
  { typed: '_hi there_', mark: 'em', md: 'a _hi there_\n' },
  { typed: '**hi there**', mark: 'strong', md: 'a **hi there**\n' },
  { typed: '__hi there__', mark: 'strong', md: 'a __hi there__\n' },
  { typed: '`hi there`', mark: 'code', md: 'a `hi there`\n' },
];

for (const c of cases) {
  test(`typing "${c.typed}" converts to ${c.mark} and round-trips`, () =>
    withEd('a\n', (ed) => {
      caret(ed, 2);
      type(ed, ' ' + c.typed);
      assert.deepEqual(runs(ed), [['a ', []], ['hi there', [c.mark]]]);
      const md = ed.getMarkdown();
      assert.equal(md, c.md);
      roundTrips(md);
      // Stored mark cleared: further typing is plain.
      type(ed, 'z');
      assert.deepEqual(runs(ed).at(-1), ['z', []]);
    }));
}

test('strikethrough is skipped: the schema has no strike mark', () => {
  assert.equal(schema.marks.strike ?? schema.marks.strikethrough, undefined);
  return withEd('a\n', (ed) => {
    caret(ed, 2);
    type(ed, ' ~~x~~');
    assert.deepEqual(runs(ed), [['a ~~x~~', []]]);
  });
});

const negatives = [
  ['empty **', '**'], ['empty __', '__'], ['empty ``', '``'],
  ['leading space', '* x*'], ['trailing space', '*x *'], ['leading space _', '_ x_'],
  ['snake_case', 'snake_case_'], ['strong with inner space end', '**x **'],
];
for (const [name, typed] of negatives) {
  test(`no conversion: ${name}`, () =>
    withEd('a\n', (ed) => {
      caret(ed, 2);
      type(ed, ' ' + typed);
      assert.deepEqual(runs(ed), [['a ' + typed, []]]);
    }));
}

test('inactive inside a code block and inside inline code', async () => {
  await withEd('```\nx\n```\n', (ed) => {
    caret(ed, 2);
    type(ed, '*y*');
    assert.equal(ed.view.state.doc.firstChild.type.name, 'code_block');
    assert.equal(ed.view.state.doc.firstChild.textContent, 'x*y*');
  });
  await withEd('`ab`\n', (ed) => {
    caret(ed, 2);
    type(ed, '*q*');
    assert.deepEqual(runs(ed), [['a*q*b', ['code']]]);
  });
});

test('works in a heading', () =>
  withEd('# h\n', (ed) => {
    caret(ed, 2);
    type(ed, ' *e*');
    assert.equal(ed.getMarkdown(), '# h *e*\n');
  }));

test('source view: no conversion', () =>
  withEd('a *x\n', (ed) => {
    const md0 = ed.getMarkdown();
    caret(ed, 5);
    ed.showSource();
    assert.ok(!ed.view.someProp('handleTextInput', (f) => f(ed.view, 5, 5, '*')));
    ed.showRich();
    assert.equal(ed.getMarkdown(), md0);
  }));

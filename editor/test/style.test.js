// FM-07: formatting follows the file's existing conventions, so an edit-and-save diff touches only
// the lines that changed. Typed input rules keep the delimiter the writer typed (covered in
// inlinerules.test.js and blockrules.test.js); commands use the prevailing marker.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { TextSelection } = await import('@milkdown/prose/state');

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
const select = (ed, s) => {
  const { from, to } = find(ed, s);
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, from, to)));
};
/** Fire Mod-<key> through the view's keydown handlers; Mod is Ctrl off Mac (jsdom). */
function press(ed, key) {
  const ev = new window.KeyboardEvent('keydown', {
    key, code: `Key${key.toUpperCase()}`, keyCode: key.toUpperCase().charCodeAt(0),
    ctrlKey: true, bubbles: true, cancelable: true,
  });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}

async function withEd(md, fn) {
  const ed = await createEditor({ root: mount(), markdown: md });
  try { return await fn(ed); } finally { await ed.destroy(); }
}

test('Mod-b in a document that writes __strong__ uses __', () => withEd('a b c\n\n__x__\n', (ed) => {
  select(ed, 'b');
  assert.equal(press(ed, 'b'), true);
  assert.equal(ed.getMarkdown(), 'a __b__ c\n\n__x__\n');
}));

test('Mod-i in a document that writes _em_ uses _', () => withEd('a b c\n\n_x_\n', (ed) => {
  select(ed, 'b');
  assert.equal(press(ed, 'i'), true);
  assert.equal(ed.getMarkdown(), 'a _b_ c\n\n_x_\n');
}));

test('the most-used marker wins over a minority convention', () => withEd('a b c\n\n__x__ and __y__ but **z**\n', (ed) => {
  select(ed, 'b');
  assert.equal(press(ed, 'b'), true);
  assert.equal(ed.getMarkdown(), 'a __b__ c\n\n__x__ and __y__ but **z**\n');
}));

test('Mod-b in a document with no convention uses the schema default **', () => withEd('a b c\n', (ed) => {
  select(ed, 'b');
  assert.equal(press(ed, 'b'), true);
  assert.equal(ed.getMarkdown(), 'a **b** c\n');
}));

test('Mod-i in a document with no convention uses the schema default *', () => withEd('a b c\n', (ed) => {
  select(ed, 'b');
  assert.equal(press(ed, 'i'), true);
  assert.equal(ed.getMarkdown(), 'a *b* c\n');
}));

test('edit-and-save: one paragraph edit leaves every other line byte-identical', () => {
  // Synthetic multi-convention fixture: ATX heading, _em_, __strong__, - bullets, *** rule.
  const source = '# Report\n\n'
    + 'Intro with _em_ and __strong__.\n\n'
    + '- first\n- second\n\n'
    + 'A middle paragraph.\n\n'
    + '***\n\n'
    + 'A closing __note__.\n';
  return withEd(source, (ed) => {
    const { from, to } = find(ed, 'middle');
    ed.view.dispatch(ed.view.state.tr.insertText('changed middle', from, to));
    const saved = ed.getMarkdown();
    const before = source.split('\n');
    const after = saved.split('\n');
    assert.equal(after.length, before.length, `line count changed:\n${saved}`);
    const changed = after.map((l, i) => (l === before[i] ? -1 : i)).filter((i) => i >= 0);
    assert.deepEqual(changed, [before.findIndex((l) => l === 'A middle paragraph.')]);
    assert.equal(after[changed[0]], 'A changed middle paragraph.');
  });
});

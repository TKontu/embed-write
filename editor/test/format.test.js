// FM-01: Mod-b/i/e/k toggle strong, em, code and link on the selection; output checked as Markdown.
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
  const ev = new window.KeyboardEvent('keydown', { key, code: `Key${key.toUpperCase()}`, keyCode: key.toUpperCase().charCodeAt(0), ctrlKey: true, bubbles: true, cancelable: true });
  return ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)) ?? false;
}
const tick = () => new Promise((r) => setTimeout(r, 0));

for (const [key, want] of [['b', 'a **b** c\n'], ['i', 'a *b* c\n'], ['e', 'a `b` c\n']]) {
  test(`Mod-${key} toggles its mark on the selection and back`, async () => {
    const ed = await createEditor({ root: mount(), markdown: 'a b c\n' });
    try {
      const md0 = ed.getMarkdown();
      select(ed, 'b');
      assert.equal(press(ed, key), true);
      assert.equal(ed.getMarkdown(), want);
      assert.equal(press(ed, key), true);
      assert.equal(ed.getMarkdown(), md0);
    } finally { await ed.destroy(); }
  });
}

test('Mod-k adds a link from onLinkRequest and removes it on the second press', async () => {
  const asked = [];
  const ed = await createEditor({ root: mount(), markdown: 'a b c\n', onLinkRequest: (t) => { asked.push(t); return 'https://x.test'; } });
  try {
    const md0 = ed.getMarkdown();
    select(ed, 'b');
    assert.equal(press(ed, 'k'), true);
    await tick();
    assert.deepEqual(asked, ['b']);
    assert.equal(ed.getMarkdown(), 'a [b](https://x.test) c\n');
    select(ed, 'b');
    assert.equal(press(ed, 'k'), true);
    assert.equal(ed.getMarkdown(), md0);
    assert.deepEqual(asked, ['b']);
  } finally { await ed.destroy(); }
});

test('Mod-k with an async URL, null or empty result', async () => {
  for (const [ret, want] of [[Promise.resolve('https://x.test'), 'a [b](https://x.test) c\n'], [null, 'a b c\n'], ['', 'a b c\n'], [Promise.resolve(null), 'a b c\n']]) {
    const ed = await createEditor({ root: mount(), markdown: 'a b c\n', onLinkRequest: () => ret });
    try {
      select(ed, 'b');
      press(ed, 'k');
      await tick();
      assert.equal(ed.getMarkdown(), want);
    } finally { await ed.destroy(); }
  }
});

test('Mod-k removes an existing link from markdown without asking', async () => {
  const asked = [];
  const ed = await createEditor({ root: mount(), markdown: 'a [b](https://y.test) c\n', onLinkRequest: (t) => { asked.push(t); return null; } });
  try {
    select(ed, 'b');
    assert.equal(press(ed, 'k'), true);
    assert.equal(ed.getMarkdown(), 'a b c\n');
    assert.deepEqual(asked, []);
  } finally { await ed.destroy(); }
});

test('Mod-k on an empty selection or without a callback does nothing', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'a b c\n' });
  try {
    select(ed, 'b');
    assert.equal(press(ed, 'k'), false);
    assert.equal(ed.getMarkdown(), 'a b c\n');
  } finally { await ed.destroy(); }
});

test('shortcuts do not act in source view', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'a b c\n' });
  try {
    select(ed, 'b');
    ed.showSource();
    assert.equal(press(ed, 'b'), false);
    ed.showRich();
    assert.equal(ed.getMarkdown(), 'a b c\n');
  } finally { await ed.destroy(); }
});

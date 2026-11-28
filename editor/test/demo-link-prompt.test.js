// FM-01 (demo residual): Mod-k on an unlinked selection asks for an href in an in-page dialog
// (never window.prompt); OK applies it, Cancel / empty / Escape leave the Markdown unchanged.
// Drives the real demo page: index.html markup, app.js, synthetic examples/demo samples.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

const w = setupDom();
const demoDir = fileURLToPath(new URL('../demo/', import.meta.url));
const dataDir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const html = readFileSync(join(demoDir, 'index.html'), 'utf8');
document.head.innerHTML = '<style id="legend-css"></style>';
document.body.innerHTML = /<body>([\s\S]*)<\/body>/.exec(html)[1].replace(/<script[\s\S]*?<\/script>/g, '');

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
globalThis.fetch = async (url) => {
  const u = String(url);
  if (u === '/api/legend') return json(JSON.parse(readFileSync(join(dataDir, 'legend.json'), 'utf8')));
  if (u === '/api/genre') return json(JSON.parse(readFileSync(join(dataDir, 'genre.json'), 'utf8')));
  if (u === '/api/samples') return json({ samples: ['synthetic-sample-1.md'] });
  if (u === '/api/sample/synthetic-sample-1.md') return new Response(readFileSync(join(dataDir, 'synthetic-sample-1.md'), 'utf8'));
  if (u === '/api/corrections/synthetic-sample-1.md') return json([]);
  return json({ error: 'not found' }, 404);
};
let prompted = 0;
w.prompt = globalThis.prompt = () => { prompted += 1; return 'https://wrong.example'; };

const { demoState } = await import('../demo/app.js');
for (let i = 0; i < 300 && !demoState.editor; i += 1) await new Promise((r) => setTimeout(r, 10));

const tick = () => new Promise((r) => setTimeout(r, 0));

const dialog = () => /** @type {HTMLElement} */ (document.getElementById('link-dialog'));
const input = () => /** @type {HTMLInputElement} */ (document.getElementById('link-href'));

/** Select the first word of the first paragraph and press Mod-k (Ctrl on jsdom). */
async function selectAndModK() {
  const { view } = demoState.editor;
  const { TextSelection } = await import('@milkdown/prose/state');
  let from = -1, to = -1;
  view.state.doc.descendants((n, pos) => {
    if (from < 0 && n.isText && !n.marks.length && /^[A-Za-z]{3,}/.test(n.text)) {
      from = pos; to = pos + /^[A-Za-z]+/.exec(n.text)[0].length;
    }
  });
  assert.ok(from >= 0, 'fixture has an unmarked word');
  view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, from, to)));
  const word = view.state.doc.textBetween(from, to);
  const ev = new w.KeyboardEvent('keydown', { key: 'k', code: 'KeyK', keyCode: 75, ctrlKey: true, bubbles: true, cancelable: true });
  view.dom.dispatchEvent(ev);
  await tick();
  return word;
}

test('demo loads an editor', () => { assert.ok(demoState.editor); });

test('OK applies the typed href as a Markdown link', async () => {
  const before = demoState.editor.getMarkdown();
  const word = await selectAndModK();
  assert.equal(dialog().hidden, false, 'dialog shown');
  assert.equal(document.activeElement, input());
  input().value = 'https://example.org/x';
  document.getElementById('link-ok').click();
  await tick();
  assert.equal(dialog().hidden, true);
  const after = demoState.editor.getMarkdown();
  assert.notEqual(after, before);
  assert.ok(after.includes(`[${word}](https://example.org/x)`), after);
  assert.equal(prompted, 0);
  // undo the link so later tests start from the loaded text
  demoState.editor.view.dispatch(demoState.editor.view.state.tr.removeMark(0, demoState.editor.view.state.doc.content.size, demoState.editor.view.state.schema.marks.link));
});

for (const [name, act] of [
  ['Cancel', () => document.getElementById('link-cancel').click()],
  ['empty href', () => { input().value = '   '; document.getElementById('link-ok').click(); }],
  ['Escape', () => input().dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))],
]) {
  test(`${name} leaves the Markdown unchanged`, async () => {
    const before = demoState.editor.getMarkdown();
    await selectAndModK();
    assert.equal(dialog().hidden, false);
    input().value = name === 'empty href' ? input().value : 'https://example.org/no';
    act();
    await tick();
    assert.equal(dialog().hidden, true);
    assert.equal(demoState.editor.getMarkdown(), before);
    assert.equal(prompted, 0);
  });
}

test('Enter in the field submits', async () => {
  const word = await selectAndModK();
  input().value = 'https://example.org/enter';
  input().dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  await tick();
  assert.equal(dialog().hidden, true);
  assert.ok(demoState.editor.getMarkdown().includes(`[${word}](https://example.org/enter)`));
});

test('teardown', async () => { await demoState.editor.destroy(); });

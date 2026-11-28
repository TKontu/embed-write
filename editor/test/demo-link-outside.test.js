// FM-01 (demo residual, R251): a pointer press outside the open link dialog cancels it like Cancel;
// a press inside keeps it open; the document listener is gone after close.
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

/** @param {Element} el @param {string} key */
const press = (el, key) => {
  const ev = new w.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  el.dispatchEvent(ev);
  return ev;
};
const ok = () => document.getElementById('link-ok');
/** @param {Element} el */
const pointerDown = (el) => {
  const ev = new w.MouseEvent('mousedown', { bubbles: true, cancelable: true });
  el.dispatchEvent(ev);
  return ev;
};

test('a press outside the dialog cancels it like Cancel', async () => {
  const before = demoState.editor.getMarkdown();
  await selectAndModK();
  input().value = 'https://example.org/outside';
  pointerDown(document.body);
  await tick();
  assert.equal(dialog().hidden, true);
  assert.equal(demoState.editor.getMarkdown(), before);
  assert.equal(prompted, 0);
});

test('a press inside the dialog keeps it open', async () => {
  await selectAndModK();
  pointerDown(input());
  pointerDown(dialog());
  await tick();
  assert.equal(dialog().hidden, false);
  press(input(), 'Escape');
  await tick();
  assert.equal(dialog().hidden, true);
});

test('the document listener is removed after close', async () => {
  const word = await selectAndModK();
  input().value = 'https://example.org/after';
  ok().click();
  await tick();
  const after = demoState.editor.getMarkdown();
  assert.ok(after.includes(`[${word}](https://example.org/after)`));
  pointerDown(document.body);
  await tick();
  assert.equal(dialog().hidden, true);
  assert.equal(demoState.editor.getMarkdown(), after);
  // reopen: one outside press closes this dialog only
  await selectAndModK();
  pointerDown(document.body);
  await tick();
  assert.equal(dialog().hidden, true);
  assert.equal(demoState.editor.getMarkdown(), after);
});

test('teardown', async () => { await demoState.editor.destroy(); });

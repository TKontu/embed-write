// ED-04 (demo residual): Mod-Shift-m toggles rich/source view from anywhere on the page, through
// the same toggleSource as the "Source view" button. Inert while #link-dialog is open and on repeat.
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
const sample = readFileSync(join(dataDir, 'synthetic-sample-1.md'), 'utf8');
document.head.innerHTML = '<style id="legend-css"></style>';
document.body.innerHTML = /<body>([\s\S]*)<\/body>/.exec(html)[1].replace(/<script[\s\S]*?<\/script>/g, '');

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
globalThis.fetch = async (url) => {
  const u = String(url);
  if (u === '/api/legend') return json(JSON.parse(readFileSync(join(dataDir, 'legend.json'), 'utf8')));
  if (u === '/api/genre') return json(JSON.parse(readFileSync(join(dataDir, 'genre.json'), 'utf8')));
  if (u === '/api/samples') return json({ samples: ['synthetic-sample-1.md'] });
  if (u === '/api/sample/synthetic-sample-1.md') return new Response(sample);
  if (u === '/api/corrections/synthetic-sample-1.md') return json([]);
  return json({ error: 'not found' }, 404);
};

const { demoState } = await import('../demo/app.js');
for (let i = 0; i < 300 && !demoState.editor; i += 1) await new Promise((r) => setTimeout(r, 10));

const button = () => /** @type {HTMLButtonElement} */ (document.getElementById('source-btn'));
const textarea = () => /** @type {HTMLTextAreaElement|null} */ (document.querySelector('textarea.md-source'));
const status = () => document.getElementById('status');
const visible = (el) => !!el && !el.hidden && el.style.display !== 'none';

/** Press Ctrl+Shift+M on the given target (default document.body). */
function press(target = document.body, extra = {}) {
  const ev = new w.KeyboardEvent('keydown', { key: 'M', code: 'KeyM', keyCode: 77, ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true, ...extra });
  target.dispatchEvent(ev);
  return ev;
}

test('Ctrl+Shift+M toggles source and rich view; round trip is byte-exact', () => {
  assert.equal(demoState.editor.isSourceView(), false);
  const ev = press();
  assert.equal(demoState.editor.isSourceView(), true);
  assert.ok(ev.defaultPrevented);
  assert.ok(visible(textarea()), 'md-source visible');
  assert.equal(button().textContent, 'Rich view');
  assert.equal(textarea().value, sample, 'source equals file byte for byte');
  press(demoState.editor.view.dom);
  assert.equal(demoState.editor.isSourceView(), false);
  assert.equal(button().textContent, 'Source view');
  press(textarea());
  assert.equal(textarea().value, sample, 'after round trip still byte-exact');
  press(textarea());
  assert.equal(demoState.editor.isSourceView(), false);
});

test('repeat and plain Ctrl+M do nothing', () => {
  press(document.body, { repeat: true });
  assert.equal(demoState.editor.isSourceView(), false);
  press(document.body, { shiftKey: false, key: 'm' });
  assert.equal(demoState.editor.isSourceView(), false);
});

test('no toggle while the link dialog is open', () => {
  const dialog = document.getElementById('link-dialog');
  dialog.hidden = false;
  try {
    press();
    assert.equal(demoState.editor.isSourceView(), false);
  } finally { dialog.hidden = true; }
});

test('failing showRich keeps source view and shows the error status', () => {
  press();
  assert.equal(demoState.editor.isSourceView(), true);
  const orig = demoState.editor.showRich;
  demoState.editor.showRich = () => { throw new Error('bad parse'); };
  try {
    press();
    assert.equal(demoState.editor.isSourceView(), true);
    assert.match(status().textContent, /Cannot leave source view: bad parse/);
    assert.equal(button().textContent, 'Rich view');
  } finally { demoState.editor.showRich = orig; }
  press();
  assert.equal(demoState.editor.isSourceView(), false);
});

// IN-01 (demo): hover or selection inside a move mark shows signal, value, confidence, layer and a
// Method link to the genre definition; no mark shows "No signal here".
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { moveOverlayPlugin } = await import('../demo/overlay.js');
const { inspectSignal, inspectorPlugin, mountInspector, renderInspector, renderMethodTexts, signalAttrs } =
  await import('../src/inspector.js');
const { Plugin, TextSelection } = await import('@milkdown/prose/state');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const name = 'synthetic-sample-1.md';
const source = readFileSync(join(dir, name), 'utf8');
const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const contextDef = genre.moves.find((m) => m.id === 'context').definition;

const overlayAttrs = (kind) => ({
  'data-signal-kind': kind, 'data-signal-layer': 'provisional', 'data-signal-confidence': '1',
  'data-signal-strength': 'strong', 'data-signal-overlay': 'moves', 'data-signal-level': 'paragraph',
  'data-move': kind,
});

test('(a) inspectSignal on overlay attrs for context', () => {
  assert.deepEqual(inspectSignal(overlayAttrs('context'), genre), {
    signal: 'Move', value: 'Context', confidence: '1', layer: 'provisional',
    methodId: 'context', methodText: contextDef,
  });
});

test('(b) unknown move id does not throw', () => {
  const info = inspectSignal(overlayAttrs('nosuch'), genre);
  assert.equal(info.value, 'nosuch');
  assert.equal(info.methodText, 'No method text for this signal');
  assert.equal(inspectSignal(null, genre), null);
  assert.equal(inspectSignal({}, genre), null);
  assert.doesNotThrow(() => inspectSignal(overlayAttrs('context'), null));
});

test('(c) renderInspector shows the four fields and a link to a method anchor', () => {
  const el = renderInspector(document, inspectSignal(overlayAttrs('context'), genre));
  assert.equal(el.tagName, 'ASIDE');
  assert.equal(el.getAttribute('aria-live'), 'polite');
  const field = (k) => el.querySelector(`dd[data-field="${k}"]`).textContent;
  assert.equal(field('signal'), 'Move');
  assert.equal(field('value'), 'Context');
  assert.equal(field('confidence'), '1');
  assert.equal(field('layer'), 'provisional');
  assert.doesNotMatch(el.textContent, /\bcorrect\b/i);
  assert.match(el.textContent, /Pattern fit, not a verdict/);
  const href = el.querySelector('a').getAttribute('href');
  const methods = renderMethodTexts(document, genre);
  const anchor = methods.querySelector(href);
  assert.ok(anchor, `no anchor for ${href}`);
  assert.equal(anchor.nextElementSibling.textContent, contextDef);
  assert.equal(methods.querySelectorAll('dt[id^="method-"]').length, genre.moves.length);
});

test('(d) null renders "No signal here"', () => {
  const el = renderInspector(document, null);
  assert.equal(el.textContent, 'No signal here');
  assert.equal(el.querySelector('a'), null);
});

test('(e) demo wiring: mouseover on a decorated block and selection update the panel', async () => {
  const root = document.body.appendChild(document.createElement('div'));
  const mount = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: source });
  try {
    const view = editor.view;
    const inspector = mountInspector(view.dom, mount, () => genre);
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins,
      moveOverlayPlugin(() => moves, () => genre), inspectorPlugin(Plugin, () => inspector)] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    const block = root.querySelector('[data-signal-kind]');
    assert.ok(block);
    assert.deepEqual(inspectSignal(signalAttrs(block), genre)?.layer, 'provisional');
    const target = block.firstChild && block.firstChild.nodeType === 1 ? block.firstChild : block;
    target.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    const kind = block.getAttribute('data-signal-kind');
    const expected = genre.moves.find((m) => m.id === kind).name;
    assert.equal(mount.querySelector('dd[data-field="value"]').textContent, expected);
    assert.equal(mount.querySelector('a').getAttribute('href'), `#method-${kind}`);

    view.dom.dispatchEvent(new window.MouseEvent('mouseleave'));
    // Selection inside the first decorated block shows it too.
    let pos = 0; let i = 0;
    for (; i < view.state.doc.childCount; i += 1) {
      const dom = view.nodeDOM(pos);
      if (dom && dom.nodeType === 1 && dom.closest('[data-signal-kind]')) break;
      pos += view.state.doc.child(i).nodeSize;
    }
    view.dispatch(view.state.tr.setSelection(TextSelection.near(view.state.doc.resolve(pos + 1))));
    assert.ok(mount.querySelector('dd[data-field="signal"]'), mount.textContent);
    inspector.destroy();
  } finally {
    await editor.destroy();
    root.remove();
    mount.remove();
  }
});

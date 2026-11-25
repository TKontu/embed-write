// RE-01: signal decorations through a ProseMirror DecorationSet.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, signalDecorations, signalDecorationsPlugin } = await import('../src/index.js');
const { parseMarkdown, assignIds } = await import('docmodel');

const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n'));
const blocks = [];
doc.descendants((n, pos) => { if (n.attrs.id) blocks.push({ id: n.attrs.id, pos, node: n }); });
const sig = (node_id, over = {}) => ({ node_id, level: 'paragraph', kind: 'readability', value: 1,
  confidence: 0.5, method_ref: 'm@1', layer: 'provisional', ...over });

test('decoration lands on the matching node with data attributes and class', () => {
  const b = blocks[1];
  const found = signalDecorations(doc, [sig(b.id)]).find();
  assert.equal(found.length, 1);
  const d = found[0];
  assert.equal(d.from, b.pos);
  assert.equal(d.to, b.pos + b.node.nodeSize);
  assert.deepEqual(d.type.attrs, { 'data-signal-kind': 'readability', 'data-signal-layer': 'provisional',
    'data-signal-confidence': '0.5', class: 'signal signal-provisional' });
});

test('unknown node_id is skipped', () => {
  assert.equal(signalDecorations(doc, [sig('NOPE')]).find().length, 0);
});

test('bad layer and bad confidence throw', () => {
  const id = blocks[0].id;
  assert.throws(() => signalDecorations(doc, [sig(id, { layer: 'final' })]));
  for (const c of [NaN, -0.1, 1.5, '0.5', Infinity, undefined]) {
    assert.throws(() => signalDecorations(doc, [sig(id, { confidence: c })]), String(c));
  }
});

test('two signals on two nodes give two decorations', () => {
  const s = [sig(blocks[1].id), sig(blocks[2].id, { layer: 'confirmed', confidence: 1 })];
  assert.equal(signalDecorations(doc, s).find().length, 2);
});

test('plugin with a view renders the attributes on the DOM element', async () => {
  const ed = await createEditor({ root: document.body.appendChild(document.createElement('div')),
    markdown: '# Title\n\nFirst para.\n\nSecond para.\n' });
  try {
    ed.view.dispatch(ed.view.state.tr.setMeta('touch', true)); // let idPlugin assign ids
    let target = null;
    ed.view.state.doc.descendants((n) => { if (!target && n.textContent === 'Second para.' && n.attrs.id) target = n.attrs.id; });
    assert.ok(target);
    const plugin = signalDecorationsPlugin(() => [sig(target, { layer: 'confirmed', confidence: 0.25 })]);
    ed.view.updateState(ed.view.state.reconfigure({ plugins: [...ed.view.state.plugins, plugin] }));
    const els = ed.view.dom.querySelectorAll('[data-signal-kind]');
    assert.equal(els.length, 1);
    const el = els[0];
    assert.equal(el.getAttribute('data-signal-layer'), 'confirmed');
    assert.equal(el.getAttribute('data-signal-confidence'), '0.25');
    assert.ok(el.classList.contains('signal') && el.classList.contains('signal-confirmed'));
    assert.match(el.textContent, /Second para/);
  } finally { await ed.destroy(); }
});

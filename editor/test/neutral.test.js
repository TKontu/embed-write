// LG-06: neutral rendering for `other` and for unlabeled text. `other` takes legend.other; text
// with no signal, and a signal whose kind is neither a genre move nor `other`, get no tint
// (transparent) — no colour is invented (I3). Legend CSS (LG-02) plus signals.css (RE-04) applied.
// Synthetic genre fixture (LLM-built): placeholder colours, not an expert palette (LG-01 is [H]).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, signalDecorationsPlugin, legendCss } = await import('../src/index.js');

const genre = () => ({
  genre: 'synthetic-fixture',
  version: 1,
  moves: [{ id: 'thesis', name: 'Thesis' }, { id: 'evidence', name: 'Evidence' }],
  legend: { colors: { thesis: '#1a2b3c', evidence: '#4d5e6f' }, other: '#7a8b9c' },
});
const MOVE_COLOURS = ['#1a2b3c', '#4d5e6f'];
const signalsCss = readFileSync(new URL('../src/signals.css', import.meta.url), 'utf8');

const signal = (node_id, kind) => ({ node_id, kind, level: 'paragraph', value: 1,
  confidence: 0.9, method_ref: 'm@1', layer: 'confirmed' });

/**
 * Render a doc with both stylesheets, decorate the "Target" block as `kind` (null: no signal),
 * and return the computed state of the Target block and of the unsignalled "Plain" block.
 */
async function render(kind) {
  const root = document.body.appendChild(document.createElement('div'));
  const style = document.createElement('style');
  style.textContent = `${legendCss(genre())}${signalsCss}`;
  document.head.appendChild(style);
  const ed = await createEditor({ root, markdown: '# Title\n\nTarget block.\n\nPlain block.\n' });
  try {
    ed.view.dispatch(ed.view.state.tr.setMeta('touch', true));
    let target = null;
    ed.view.state.doc.descendants((n) => {
      if (!target && n.textContent.startsWith('Target') && n.attrs.id) target = n.attrs.id;
    });
    assert.ok(target, 'target block has an id');
    const sigs = kind === null ? [] : [signal(target, kind)];
    const plugin = signalDecorationsPlugin(() => sigs);
    ed.view.updateState(ed.view.state.reconfigure({ plugins: [...ed.view.state.plugins, plugin] }));
    const read = (prefix) => {
      const el = [...ed.view.dom.querySelectorAll('p')].find((p) => p.textContent.startsWith(prefix));
      assert.ok(el, `${prefix} block rendered`);
      const cs = getComputedStyle(el);
      return { el, color: cs.getPropertyValue('--signal-color').trim(), bg: cs.backgroundColor };
    };
    return { target: read('Target'), plain: read('Plain') };
  } finally {
    style.remove();
    await ed.destroy();
  }
}

test('(1) kind "other" renders with legend.other, never a move colour', async () => {
  const { target } = await render('other');
  assert.equal(target.el.getAttribute('data-signal-kind'), 'other');
  assert.equal(target.color, '#7a8b9c');
  assert.ok(!MOVE_COLOURS.includes(target.color));
});

test('(2) unlabeled text has no signal class and no tint', async () => {
  for (const kind of [null, 'thesis']) {
    const { plain } = await render(kind);
    assert.ok(!plain.el.classList.contains('signal'), 'no signal class');
    assert.equal(plain.el.hasAttribute('data-signal-kind'), false);
    assert.equal(plain.color, '', 'no --signal-color');
    assert.ok(['', 'transparent', 'rgba(0, 0, 0, 0)'].includes(plain.bg), `no tint: ${plain.bg}`);
  }
});

test('(3) unknown kind renders neutral: no --signal-color, so the tint falls back to transparent', async () => {
  for (const kind of ['unknown-move', 'Thesis', '']) {
    const { target } = await render(kind);
    assert.ok(target.el.classList.contains('signal'));
    assert.equal(target.color, '', `kind ${JSON.stringify(kind)} gets no colour`);
    assert.ok(!MOVE_COLOURS.includes(target.color) && target.color !== '#7a8b9c');
  }
});

test('(3) the tint rule falls back to transparent when --signal-color is unset', () => {
  const code = signalsCss.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(code, /var\(--signal-color,\s*transparent\)/);
});

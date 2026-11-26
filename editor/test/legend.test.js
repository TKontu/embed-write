// LG-02: the legend is read from the genre file; CSS is emitted from stored colours only (I3).
// Synthetic genre fixture (LLM-built): placeholder colours, not an expert palette (LG-01 is [H]).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, signalDecorationsPlugin, legendCss } = await import('../src/index.js');

/** @returns {any} a parsed genre file shaped like service/genre.py accepts */
const genre = () => ({
  genre: 'synthetic-fixture',
  version: 1,
  moves: [
    { id: 'thesis', name: 'Thesis' },
    { id: 'evidence', name: 'Evidence' },
  ],
  legend: {
    colors: { thesis: '#1A2B3C', evidence: '#4d5e6f' },
    other: '#7A8B9C',
  },
});

const signal = (node_id, kind = 'thesis') => ({ node_id, kind, level: 'paragraph', value: 1,
  confidence: 0.9, method_ref: 'm@1', layer: 'confirmed' });

/** Assert `fn` throws our own Error whose message names `field` (service/genre.py style). */
function assertFieldError(fn, field) {
  let err;
  try { fn(); } catch (e) { err = e; }
  assert.ok(err instanceof Error, 'throws an Error');
  assert.equal(err.constructor, Error, `plain Error, not ${err.constructor.name}`);
  assert.ok(err.message.startsWith(`${field}:`), `message names ${field}: ${err.message}`);
}

/**
 * Render `markdown`, decorate the block whose text starts with "Target" as move `kind`, apply
 * `css` as a stylesheet, and return the element's computed --signal-color.
 */
async function renderedColor(markdown, css, kind = 'thesis') {
  const root = document.body.appendChild(document.createElement('div'));
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
  const ed = await createEditor({ root, markdown });
  try {
    ed.view.dispatch(ed.view.state.tr.setMeta('touch', true)); // let idPlugin assign ids
    let target = null;
    ed.view.state.doc.descendants((n) => {
      if (!target && n.textContent.startsWith('Target') && n.attrs.id) target = n.attrs.id;
    });
    assert.ok(target, 'target block has an id');
    const plugin = signalDecorationsPlugin(() => [signal(target, kind)]);
    ed.view.updateState(ed.view.state.reconfigure({ plugins: [...ed.view.state.plugins, plugin] }));
    const el = ed.view.dom.querySelector(`[data-signal-kind="${kind}"]`);
    assert.ok(el, 'decorated node is rendered');
    return getComputedStyle(el).getPropertyValue('--signal-color').trim();
  } finally {
    style.remove();
    await ed.destroy();
  }
}

test('emits one rule per move in genre.moves order, then other, with the stored colours', () => {
  const css = legendCss(genre());
  assert.equal(css, [
    '.signal[data-signal-kind="thesis"] { --signal-color: #1a2b3c; }',
    '.signal[data-signal-kind="evidence"] { --signal-color: #4d5e6f; }',
    '.signal[data-signal-kind="other"] { --signal-color: #7a8b9c; }',
    '',
  ].join('\n'));
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
  try {
    const rules = [...document.styleSheets[document.styleSheets.length - 1].cssRules];
    assert.deepEqual(rules.map((r) => r.selectorText), [
      '.signal[data-signal-kind="thesis"]',
      '.signal[data-signal-kind="evidence"]',
      '.signal[data-signal-kind="other"]',
    ]);
    assert.deepEqual(rules.map((r) => r.style.getPropertyValue('--signal-color')),
      ['#1a2b3c', '#4d5e6f', '#7a8b9c']);
  } finally { style.remove(); }
});

test('two different documents of one genre render the same move with the same colour', async () => {
  const css = legendCss(genre());
  const first = await renderedColor('# One\n\nTarget sentence in the first document.\n\nOther text.\n', css);
  const second = await renderedColor('# Two\n\nA different opening block.\n\nTarget sentence in the second document.\n', css);
  assert.equal(first, '#1a2b3c');
  assert.equal(second, '#1a2b3c');
  assert.equal(first, second);
});

test('output is byte-identical across calls and independent of colors key order', () => {
  const a = genre();
  const b = genre();
  b.legend.colors = { evidence: '#4d5e6f', thesis: '#1a2b3c' };
  assert.deepEqual(Object.keys(b.legend.colors), ['evidence', 'thesis']);
  assert.equal(legendCss(a), legendCss(a));
  assert.equal(legendCss(a), legendCss(b));
});

test('throws naming legend when legend is missing or not an object', () => {
  for (const legend of [undefined, null, '#fff', []]) {
    const g = genre();
    if (legend === undefined) delete g.legend; else g.legend = legend;
    assertFieldError(() => legendCss(g), 'legend');
  }
});

test('throws naming legend.colors when colors is missing or not an object', () => {
  for (const colors of [undefined, null, '#fff', []]) {
    const g = genre();
    if (colors === undefined) delete g.legend.colors; else g.legend.colors = colors;
    assertFieldError(() => legendCss(g), 'legend.colors');
  }
});

test('throws naming legend.other when the neutral colour is missing or invalid', () => {
  const missing = genre();
  delete missing.legend.other;
  assertFieldError(() => legendCss(missing), 'legend.other');
  for (const other of [undefined, null, 'red', '#12345', '#1234567', 123456]) {
    const g = genre();
    g.legend.other = other;
    assertFieldError(() => legendCss(g), 'legend.other');
  }
});

test('throws naming the move when a move has no colour or its colour is invalid', () => {
  const missing = genre();
  delete missing.legend.colors.thesis;
  assertFieldError(() => legendCss(missing), 'legend.colors.thesis');
  for (const bad of ['#12345', '123456', '#12345g', '#1234567', 'red', null, undefined, 16711680]) {
    const g = genre();
    g.legend.colors.thesis = bad;
    assertFieldError(() => legendCss(g), 'legend.colors.thesis');
  }
});

test('throws naming an unknown colors key that is not a move id', () => {
  const g = genre();
  g.legend.colors.mystery = '#000000';
  assertFieldError(() => legendCss(g), 'legend.colors.mystery');
});

test('comment keys starting with _ are ignored, mirroring service/genre.py', () => {
  const g = genre();
  g.legend.colors._note = 'not a colour';
  assert.equal(legendCss(g), legendCss(genre()));
});

test('every hex in the output appears in the genre legend, and the source generates no colour', () => {
  const g = genre();
  const out = legendCss(g);
  const stored = new Set([...Object.values(g.legend.colors), g.legend.other].map((v) => v.toLowerCase()));
  const emitted = out.match(/#[0-9a-f]{6}/g) ?? [];
  assert.ok(emitted.length >= g.moves.length + 1);
  for (const hex of emitted) assert.ok(stored.has(hex), `emitted ${hex} is stored in the genre file`);
  const src = readFileSync(fileURLToPath(new URL('../src/legend.js', import.meta.url)), 'utf8');
  assert.doesNotMatch(src, /hsl|hsla|random|hash/i);
});

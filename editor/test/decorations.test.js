// RE-01: signal decorations through a ProseMirror DecorationSet.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
import { readFileSync } from 'node:fs';
const { createEditor, signalDecorations, signalDecorationsPlugin, DEFAULT_WEAK_BELOW } = await import('../src/index.js');
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
    'data-signal-confidence': '0.5', 'data-signal-strength': 'strong',
    class: 'signal signal-provisional signal-strong' });
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
    assert.equal(el.getAttribute('data-signal-strength'), 'weak');
    assert.ok(el.classList.contains('signal-weak'));
    assert.match(el.textContent, /Second para/);
  } finally { await ed.destroy(); }
});

// RE-08: strength rendering from confidence.
const strength = (c, opts) => signalDecorations(doc, [sig(blocks[1].id, { confidence: c })], opts).find()[0].type.attrs;

test('default threshold: 0.2 weak, 0.5 and 0.9 strong', () => {
  assert.equal(DEFAULT_WEAK_BELOW, 0.5);
  assert.equal(strength(0.2)['data-signal-strength'], 'weak');
  assert.match(strength(0.2).class, /\bsignal-weak\b/);
  for (const c of [0.5, 0.9]) {
    assert.equal(strength(c)['data-signal-strength'], 'strong');
    assert.match(strength(c).class, /\bsignal-strong\b/);
  }
});

test('custom weakBelow 0.8 makes 0.5 weak', () => {
  assert.equal(strength(0.5, { weakBelow: 0.8 })['data-signal-strength'], 'weak');
  assert.equal(strength(0.8, { weakBelow: 0.8 })['data-signal-strength'], 'strong');
});

test('bad weakBelow throws', () => {
  for (const w of [NaN, -0.1, 1.1, Infinity, '0.5', null]) {
    assert.throws(() => strength(0.5, { weakBelow: w }), String(w));
  }
});

test('signals.css is opacity-only, weak lower than strong', () => {
  const css = readFileSync(new URL('../src/signals.css', import.meta.url), 'utf8');
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(bare, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(bare, /\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\s*\(/i);
  assert.doesNotMatch(bare, /(^|[\s;{])(color|background(-color)?|border(-color)?|outline(-color)?|fill|stroke)\s*:/im);
  const op = (cls) => {
    const m = bare.match(new RegExp(`\\.${cls}\\s*\\{([^}]*)\\}`));
    assert.ok(m, cls);
    const v = m[1].match(/opacity\s*:\s*([0-9.]+)/);
    assert.ok(v, `${cls} opacity`);
    return Number(v[1]);
  };
  assert.ok(op('signal-weak') < op('signal-strong'));
});

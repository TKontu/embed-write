// RE-04: paragraph and sentence level signals are tinted by move via --signal-color only (I3).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setupDom } from './dom.js';

setupDom();
const { signalDecorations } = await import('../src/index.js');
const { parseMarkdown, assignIds } = await import('docmodel');

const css = readFileSync(new URL('../src/signals.css', import.meta.url), 'utf8');
const code = css.replace(/\/\*[\s\S]*?\*\//g, '');
const rules = [...code.matchAll(/([^{}]+)\{([^}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const tintRule = (level) => rules.find((r) => r.sel.split(',').map((s) => s.trim())
  .includes(`.signal[data-signal-level="${level}"]`));

for (const level of ['paragraph', 'sentence']) {
  test(`${level} level sets background from var(--signal-color, transparent)`, () => {
    const r = tintRule(level);
    assert.ok(r, `no rule for ${level}`);
    assert.match(r.body, /background(-color)?\s*:[^;]*var\(--signal-color,\s*transparent\)/);
  });
}

test('section level is not tinted (RE-03 ribbon)', () => {
  assert.ok(!/data-signal-level="section"/.test(code));
});

test('no literal colours outside comments (I3)', () => {
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(code), 'hex colour');
  assert.ok(!/\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i.test(code), 'colour function');
});

test('RE-08 opacity rules unchanged', () => {
  assert.match(code, /\.signal-strong\s*\{\s*opacity:\s*1;\s*\}/);
  assert.match(code, /\.signal-weak\s*\{\s*opacity:\s*0\.55;\s*\}/);
});

test('a decorated paragraph node matches the tint selector; section does not', () => {
  const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n'));
  const ids = [];
  doc.descendants((n) => { if (n.attrs.id) ids.push(n.attrs.id); });
  const sig = (node_id, level) => ({ node_id, level, kind: 'claim', value: 1, confidence: 0.9,
    method_ref: 'm@1', layer: 'provisional' });
  const el = (level) => {
    const [d] = signalDecorations(doc, [sig(ids[1], level)]).find();
    const e = document.createElement('p');
    for (const [k, v] of Object.entries(d.type.attrs)) e.setAttribute(k, v);
    return e;
  };
  for (const level of ['paragraph', 'sentence']) assert.ok(el(level).matches(tintRule(level).sel));
  const section = el('section');
  for (const level of ['paragraph', 'sentence']) assert.ok(!section.matches(tintRule(level).sel));
});

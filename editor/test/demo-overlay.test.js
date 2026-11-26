// DE-02/DE-06: the provisional overlay renders one decoration per labelled block; the legend panel
// is renderLegendPanel's output and each decoration's colour comes from a legendCss rule, both read
// from the synthetic genre file examples/demo/genre.json (I3).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { legendCss, renderLegendPanel } = await import('../src/legend.js');
const { moveDecorations, moveOverlayPlugin, genreMoveIds } = await import('../demo/overlay.js');
const { parseMarkdown, assignIds } = await import('docmodel');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const name = 'synthetic-sample-1.md';
const source = readFileSync(join(dir, name), 'utf8');
const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));

/** Parse legendCss output into kind -> colour, failing on any line that is not a single rule. */
function cssRules(css) {
  const rules = new Map();
  for (const line of css.trim().split('\n')) {
    const m = /^\.signal\[data-signal-kind="([^"]+)"\] \{ --signal-color: (#[0-9a-f]{6}); \}$/.exec(line);
    assert.ok(m, `unexpected legendCss line: ${line}`);
    rules.set(m[1], m[2]);
  }
  return rules;
}

test('one decoration per labelled block carries the move kind and no colour of its own', () => {
  const doc = assignIds(parseMarkdown(source));
  const found = moveDecorations(doc, moves, genre).find();
  assert.equal(found.length, moves.length);
  for (let i = 0; i < moves.length; i++) {
    const { move } = moves[i];
    const attrs = found[i].type.attrs;
    assert.ok(new RegExp(`\\bmove-${move}\\b`).test(attrs.class), `class ${attrs.class} lacks move-${move}`);
    assert.ok(/\bsignal\b/.test(attrs.class));
    assert.ok(attrs.class.includes('signal-provisional'));
    assert.equal(attrs['data-move'], move);
    assert.equal(attrs['data-signal-kind'], move);
    assert.equal(attrs.style, undefined);
    assert.equal(attrs['data-move-colour'], undefined);
  }
});

test('demo legend panel and overlay colours come from the genre file', async () => {
  // Same wiring as editor/demo/app.js renderLegend(): stylesheet in a <style>, panel mounted.
  const style = document.head.appendChild(document.createElement('style'));
  style.textContent = legendCss(genre);
  const mount = document.body.appendChild(document.createElement('div'));
  mount.replaceChildren(renderLegendPanel(genre, { document }));
  const root = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: source });
  try {
    // (a) one entry per move in genre order plus `other`, each with its definition.
    const entries = [...mount.querySelectorAll('.legend-entry')];
    assert.deepEqual(entries.map((e) => e.getAttribute('data-signal-kind')),
      [...genre.moves.map((m) => m.id), 'other']);
    genre.moves.forEach((m, i) => {
      assert.equal(entries[i].querySelector('.legend-name').textContent, m.name);
      assert.equal(entries[i].querySelector('.legend-definition').textContent, m.definition);
      assert.equal(entries[i].querySelector('.legend-swatch').getAttribute('data-color'), genre.legend.colors[m.id]);
    });

    // (b) each labelled block's decoration is matched by a legendCss rule with the stored colour.
    const plugin = moveOverlayPlugin(() => moves, () => genre);
    editor.view.updateState(editor.view.state.reconfigure({
      plugins: [...editor.view.state.plugins, plugin],
    }));
    editor.view.dispatch(editor.view.state.tr.setMeta('demo:loaded', true));
    const rules = cssRules(style.textContent);
    assert.deepEqual([...rules.keys()], [...genreMoveIds(genre), 'other']);
    const nodes = [...root.querySelectorAll('[data-move]')];
    assert.equal(nodes.length, moves.length);
    for (const node of nodes) {
      const kind = node.getAttribute('data-signal-kind');
      const selector = `.signal[data-signal-kind="${kind}"]`;
      assert.ok(node.matches(selector), `decoration not matched by ${selector}`);
      assert.equal(rules.get(kind), genre.legend.colors[kind]);
      assert.equal(node.getAttribute('style'), null);
      // The rule is live in the document's stylesheet and matches this node.
      const sheetRule = [...style.sheet.cssRules].find((r) => r.selectorText === selector);
      assert.ok(sheetRule, `no stylesheet rule ${selector}`);
      assert.equal(sheetRule.style.getPropertyValue('--signal-color').trim(), genre.legend.colors[kind]);
    }
  } finally {
    await editor.destroy();
    root.remove();
    mount.remove();
    style.remove();
  }
});

test('the shipped genre file keeps the placeholder moves and legend.json colours', () => {
  const legend = JSON.parse(readFileSync(join(dir, 'legend.json'), 'utf8'));
  assert.equal(legend.provisional, true);
  assert.deepEqual(genreMoveIds(genre), Object.keys(legend.moves));
  for (const id of genreMoveIds(genre)) assert.equal(genre.legend.colors[id], legend.moves[id].colour);
  assert.match(genre._note, /synthetic/i);
  assert.match(genre._note, /LLM-built/);
});

test('a sidecar block outside the document is rejected', () => {
  const doc = assignIds(parseMarkdown(source));
  assert.throws(() => moveDecorations(doc, [{ block: 999, move: 'context' }], genre), /out of range/);
  assert.throws(() => moveDecorations(doc, [{ block: 0, move: 'missing' }], genre), /no genre entry/);
});

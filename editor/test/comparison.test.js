// OV-02: comparison strip — typical move order from the demo samples beside the draft's.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { moveSequence, typicalSequence, renderComparison, mountComparison } = await import('../src/comparison.js');
const { createEditor } = await import('../src/index.js');
const { mountCollapsibleMinimap } = await import('../src/minimap.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const order = genre.moves.map((m) => m.id);
const names = readdirSync(dir).filter((n) => n.endsWith('.md')).sort();
const movesOf = (n) => JSON.parse(readFileSync(join(dir, n.replace(/\.md$/, '.moves.json')), 'utf8'));

test('(a) moveSequence sorts by block and collapses repeats', () => {
  assert.deepEqual(moveSequence([
    { block: 5, move: 'finding' }, { block: 0, move: 'context' }, { block: 3, move: 'method' },
    { block: 1, move: 'context' }, { block: 4, move: 'method' }, { block: 6, move: 'finding' },
  ]), ['context', 'method', 'finding']);
  assert.deepEqual(moveSequence([]), []);
});

test('(b) typicalSequence follows the most frequent unused transition with support counts', () => {
  const r = typicalSequence([
    ['context', 'method', 'finding'],
    ['context', 'gap', 'method', 'finding'],
    ['context', 'gap', 'method', 'finding'],
  ], order);
  assert.deepEqual(r.sequence, ['context', 'gap', 'method', 'finding']);
  assert.deepEqual(r.support, [
    { from: null, to: 'context', count: 3, of: 3 },
    { from: 'context', to: 'gap', count: 2, of: 3 },
    { from: 'gap', to: 'method', count: 2, of: 2 },
    { from: 'method', to: 'finding', count: 3, of: 3 },
  ]);
});

test('(b) ties break by genre order, then id; deterministic', () => {
  const seqs = [['context', 'method'], ['context', 'gap'], ['context', 'zeta'], ['context', 'alpha']];
  const a = typicalSequence(seqs, order);
  assert.deepEqual(a.sequence, ['context', 'gap']);
  assert.deepEqual(typicalSequence([...seqs].reverse(), order), a);
  // without genre order: by id
  assert.deepEqual(typicalSequence(seqs).sequence, ['context', 'alpha']);
  // unknown ids rank after genre ids
  assert.deepEqual(typicalSequence([['context', 'zeta'], ['context', 'finding']], order).sequence, ['context', 'finding']);
  // a used move is never revisited
  assert.deepEqual(typicalSequence([['a', 'b', 'a', 'b']]).sequence, ['a', 'b']);
});

test('(c) empty input gives an empty sequence without throwing', () => {
  assert.deepEqual(typicalSequence([]), { sequence: [], support: [] });
  assert.deepEqual(typicalSequence([[], []]), { sequence: [], support: [] });
  const el = renderComparison(document, { draft: [], typical: typicalSequence([]), genre });
  assert.equal(el.querySelectorAll('.minimap').length, 2);
  assert.equal(el.querySelectorAll('.comparison-steps li').length, 0);
});

test('(d) renderComparison shows two labelled strips, count captions and no inline colours', () => {
  const typical = typicalSequence([['context', 'method', 'finding'], ['context', 'gap', 'method', 'finding'],
    ['context', 'method', 'finding']], order);
  const el = renderComparison(document, { draft: ['context', 'finding', 'oops'], typical, genre, samples: 3 });
  const labels = [...el.querySelectorAll('.comparison-label')].map((l) => l.textContent);
  assert.deepEqual(labels, ['This draft', 'Typical sequence (3 synthetic samples, LLM-built)']);
  const strips = [...el.querySelectorAll('.minimap')];
  assert.deepEqual([...strips[0].querySelectorAll('.minimap-segment')].map((s) => s.getAttribute('data-signal-kind')),
    ['context', 'finding', 'other']);
  assert.deepEqual([...strips[1].querySelectorAll('.minimap-segment')].map((s) => s.getAttribute('data-signal-kind')),
    ['context', 'method', 'finding']);
  const captions = [...el.querySelectorAll('.comparison-steps li')].map((l) => l.textContent);
  const n = (id) => genre.moves.find((m) => m.id === id).name;
  assert.equal(captions[0], `${n('context')} comes first in 3 of 3 samples`);
  assert.equal(captions[1], `${n('method')} follows ${n('context')} in 2 of 3 samples`);
  assert.match(el.textContent, /pattern fit, not a verdict/i);
  for (const node of el.querySelectorAll('*')) {
    assert.doesNotMatch(node.getAttribute('style') ?? '', /colou?r|background/i);
  }
});

test('(e) demo wiring: comparison present, typical fixed, draft strip changes on sample switch', async () => {
  // Same wiring as editor/demo/app.js load(): minimap mount, comparison mount after it.
  const minimap = document.body.appendChild(document.createElement('div'));
  const mount = document.createElement('div');
  minimap.after(mount);
  const all = names.map(movesOf);
  const root = document.body.appendChild(document.createElement('div'));
  const drafts = [];
  try {
    for (const name of names.slice(0, 2)) {
      const editor = await createEditor({ root, markdown: readFileSync(join(dir, name), 'utf8') });
      try {
        mountCollapsibleMinimap(minimap, movesOf(name), editor.view.state.doc.childCount, genre);
        mountComparison(mount, movesOf(name), all, genre);
      } finally { await editor.destroy(); }
      const el = mount.querySelector('.comparison');
      assert.ok(el);
      assert.match(el.textContent, new RegExp(`Typical sequence \\(${names.length} synthetic samples, LLM-built\\)`));
      const kinds = (sel) => [...mount.querySelectorAll(`${sel} .minimap-segment`)].map((s) => s.getAttribute('data-signal-kind')).join(',');
      drafts.push({ draft: kinds('.comparison-draft'), typical: kinds('.comparison-typical') });
    }
    assert.notEqual(drafts[0].draft, drafts[1].draft);
    assert.equal(drafts[0].typical, drafts[1].typical);
    assert.equal(drafts[0].typical, typicalSequence(all.map(moveSequence), order).sequence
      .map((id) => (order.includes(id) ? id : 'other')).join(','));
  } finally {
    minimap.remove(); mount.remove(); root.remove();
  }
});

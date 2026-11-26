// OV-01: document minimap strip. Synthetic fixtures below are LLM-built; examples/demo samples are
// the shipped synthetic demo files.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { legendCss } = await import('../src/legend.js');
const { minimapSegments, renderMinimap, mountMinimap } = await import('../src/minimap.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const ids = genre.moves.map((m) => m.id);
const strip = (segs) => segs.map((s) => `${s.move}:${s.start}+${s.count}`);

test('(a) consecutive same-move blocks merge into one run, order preserved', () => {
  const moves = [{ block: 2, move: 'gap' }, { block: 0, move: 'context' }, { block: 1, move: 'context' },
    { block: 3, move: 'context' }];
  assert.deepEqual(strip(minimapSegments(moves, 4, ids)), ['context:0+2', 'gap:2+1', 'context:3+1']);
});

test('(b) unlabeled blocks become uncoloured gap segments', () => {
  const segs = minimapSegments([{ block: 1, move: 'method' }, { block: 4, move: 'method' }], 6, ids);
  assert.deepEqual(strip(segs), ['unlabeled:0+1', 'method:1+1', 'unlabeled:2+2', 'method:4+1', 'unlabeled:5+1']);
  const el = renderMinimap(document, segs, genre);
  const gaps = [...el.querySelectorAll('.minimap-unlabeled')];
  assert.equal(gaps.length, 3);
  for (const g of gaps) {
    assert.equal(g.hasAttribute('data-signal-kind'), false);
    assert.equal(g.classList.contains('signal'), false);
  }
  assert.deepEqual(minimapSegments([], 0, ids), []);
});

test('(c) an unknown move id maps to other', () => {
  const segs = minimapSegments([{ block: 0, move: 'nope' }, { block: 1, move: 'also-nope' }], 2, ids);
  assert.deepEqual(strip(segs), ['other:0+2']);
  const seg = renderMinimap(document, segs, genre).firstElementChild;
  assert.equal(seg.getAttribute('data-signal-kind'), 'other');
  assert.equal(seg.title, 'Other');
});

test('(d) rendered segments are matched by a legendCss(genre) rule, sized by block count', () => {
  const style = document.head.appendChild(document.createElement('style'));
  style.textContent = legendCss(genre);
  try {
    const moves = JSON.parse(readFileSync(join(dir, 'synthetic-sample-1.moves.json'), 'utf8'));
    const segs = minimapSegments(moves, 10, ids);
    const el = renderMinimap(document, segs, genre);
    const coloured = [...el.querySelectorAll('[data-signal-kind]')];
    assert.ok(coloured.length > 0);
    for (const node of coloured) {
      const kind = node.getAttribute('data-signal-kind');
      const rule = [...style.sheet.cssRules].find((r) => node.matches(r.selectorText));
      assert.ok(rule, `no legendCss rule for ${kind}`);
      const want = kind === 'other' ? genre.legend.other : genre.legend.colors[kind];
      assert.equal(rule.style.getPropertyValue('--signal-color').trim(), want.toLowerCase());
      assert.equal(node.title, genre.moves.find((m) => m.id === kind).name);
    }
    [...el.children].forEach((node, i) => assert.equal(node.style.flexGrow, String(segs[i].count)));
  } finally {
    style.remove();
  }
});

test('(e) demo wiring mounts the strip for each sample and re-renders on switch', async () => {
  const mount = document.body.appendChild(document.createElement('div'));
  try {
    for (const name of ['synthetic-sample-1.md', 'synthetic-sample-2.md', 'synthetic-sample-3.md']) {
      const root = document.body.appendChild(document.createElement('div'));
      const editor = await createEditor({ root, markdown: readFileSync(join(dir, name), 'utf8') });
      try {
        const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
        const blocks = editor.view.state.doc.childCount;
        mountMinimap(mount, moves, blocks, genre);
        assert.equal(mount.querySelectorAll('.minimap').length, 1);
        const segs = [...mount.querySelectorAll('.minimap-segment')];
        assert.equal(segs.reduce((n, s) => n + Number(s.style.flexGrow), 0), blocks);
        const labelled = new Set(moves.filter((m) => m.block < blocks).map((m) => m.block)).size;
        const coloured = segs.filter((s) => s.hasAttribute('data-signal-kind'));
        assert.equal(coloured.reduce((n, s) => n + Number(s.dataset.count), 0), labelled);
      } finally {
        await editor.destroy();
        root.remove();
      }
    }
  } finally {
    mount.remove();
  }
});

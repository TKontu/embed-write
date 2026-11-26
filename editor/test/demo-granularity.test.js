// RE-09 (demo): the granularity select chooses section / paragraph / sentence; only the selected
// level's provisional labels are decorated. Synthetic, LLM-built samples only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, DEFAULT_GRANULARITY } = await import('../src/index.js').then(async (m) => ({
  ...m, ...(await import('../src/decorations.js')),
}));
const { moveOverlayPlugin, moveOverlayKey, moveDecorations, setMoveGranularity, selectedMoveGranularity,
  toggleMoveOverlay, isMoveOverlayOn, splitSentences } = await import('../demo/overlay.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const name = 'synthetic-sample-3.md';
const source = readFileSync(join(dir, name), 'utf8');
const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));

async function open(getMoves = () => moves, opts = {}) {
  const root = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: source });
  const view = editor.view;
  view.updateState(view.state.reconfigure({
    plugins: [...view.state.plugins, moveOverlayPlugin(getMoves, () => genre, opts)],
  }));
  view.dispatch(view.state.tr.setMeta('demo:loaded', true));
  return { root, editor, view, close: async () => { await editor.destroy(); root.remove(); } };
}
const decos = (state) => moveOverlayKey.get(state).props.decorations.call(null, state).find();
const top = (doc) => { const t = []; doc.forEach((node, offset) => t.push({ node, offset })); return t; };
const levelOf = (e) => e.level ?? 'paragraph';

test('sample sidecar has entries at every level', () => {
  for (const l of ['section', 'paragraph', 'sentence']) assert.ok(moves.some((e) => levelOf(e) === l), l);
});

test('default paragraph decorates only paragraph-level entries', async () => {
  const t = await open();
  try {
    assert.equal(DEFAULT_GRANULARITY, 'paragraph');
    assert.equal(selectedMoveGranularity(t.view.state), 'paragraph');
    const blocks = top(t.view.state.doc);
    const want = moves.filter((e) => levelOf(e) === 'paragraph' && (e.overlay ?? 'moves') === 'moves')
      .map((e) => [blocks[e.block].offset, blocks[e.block].offset + blocks[e.block].node.nodeSize]);
    const got = decos(t.view.state).map((d) => [d.from, d.to]);
    assert.deepEqual(got.sort((a, b) => a[0] - b[0]), want.sort((a, b) => a[0] - b[0]));
    for (const d of decos(t.view.state)) assert.equal(d.type.attrs['data-signal-level'], 'paragraph');
    assert.equal(t.root.querySelectorAll('[data-signal-level="paragraph"]').length, want.length);
  } finally { await t.close(); }
});

test('section decorates the heading span only for section entries; no doc steps', async () => {
  const t = await open();
  try {
    let steps = -1;
    const before = JSON.stringify(t.view.state.doc.toJSON());
    assert.equal(setMoveGranularity('section')(t.view.state, (tr) => { steps = tr.steps.length; t.view.dispatch(tr); }), true);
    assert.equal(steps, 0);
    assert.equal(JSON.stringify(t.view.state.doc.toJSON()), before);
    assert.equal(selectedMoveGranularity(t.view.state), 'section');
    const blocks = top(t.view.state.doc);
    const expected = [];
    for (const e of moves.filter((m) => levelOf(m) === 'section')) {
      const rank = blocks[e.block].node.attrs.level;
      for (let i = e.block; i < blocks.length; i++) {
        const n = blocks[i].node;
        if (i > e.block && n.type.name === 'heading' && n.attrs.level <= rank) break;
        expected.push({ from: blocks[i].offset, move: e.move });
      }
    }
    // sample 3: "## Gap" (block 4) runs through block 9 (h3 is lower rank), "## Finding" to the end.
    assert.deepEqual(expected.map((x) => x.from), [4, 5, 6, 7, 8, 9, 10, 11].map((i) => blocks[i].offset));
    const got = decos(t.view.state).map((d) => ({ from: d.from, move: d.type.attrs['data-move'], level: d.type.attrs['data-signal-level'] }));
    assert.deepEqual(got.sort((a, b) => a.from - b.from), expected.map((x) => ({ ...x, level: 'section' })));
    for (const d of decos(t.view.state)) assert.equal(d.to - d.from, t.view.state.doc.nodeAt(d.from).nodeSize);
  } finally { await t.close(); }
});

test('sentence decorates an inline range equal to the sentence text', async () => {
  const two = [{ block: 1, move: 'context', level: 'sentence', sentence: 0 },
    { block: 11, move: 'finding', level: 'sentence', sentence: 0 }];
  const t = await open(() => two, { initialGranularity: 'sentence' });
  try {
    const doc = t.view.state.doc;
    const ds = decos(t.view.state).sort((a, b) => a.from - b.from);
    assert.equal(ds.length, 2);
    assert.equal(doc.textBetween(ds[0].from, ds[0].to),
      'This file is a synthetic sample and not real data; it exists only to exercise the demo.');
    assert.equal(doc.textBetween(ds[1].from, ds[1].to),
      'The synthetic result is a single documented status, not a range.');
    for (const d of ds) {
      assert.equal(d.type.attrs['data-signal-level'], 'sentence');
      assert.ok(!('style' in d.type.attrs));
    }
    assert.ok(t.root.querySelectorAll('span[data-signal-level="sentence"]').length >= 2);
  } finally { await t.close(); }
});

test('sentence splitter rule', () => {
  const s = 'One. Two! Three? Four 3.5 x';
  assert.deepEqual(splitSentences(s).map(([a, b]) => s.slice(a, b)), ['One.', 'Two!', 'Three?', 'Four 3.5 x']);
  assert.deepEqual(splitSentences('  '), []);
});

test('bad entries throw', async () => {
  const t = await open(() => []);
  try {
    const doc = t.view.state.doc;
    const run = (e, g = 'paragraph') => moveDecorations(doc, [e], genre, g);
    assert.throws(() => run({ block: 1, move: 'context', level: 'word' }), /level/);
    assert.throws(() => run({ block: 1, move: 'context', level: 'sentence' }), /sentence/);
    assert.throws(() => run({ block: 1, move: 'context', level: 'sentence', sentence: 1.5 }), /sentence/);
    assert.throws(() => run({ block: 1, move: 'context', level: 'sentence', sentence: 9 }), /out of range/);
    assert.throws(() => run({ block: 1, move: 'context', level: 'section' }, 'section'), /heading/);
    assert.throws(() => run({ block: 1, move: 'context' }, 'clause'), /level/);
    assert.throws(() => setMoveGranularity('word'), /level/);
    assert.throws(() => moveOverlayPlugin(() => [], () => genre, { initialGranularity: 'x' }), /level/);
  } finally { await t.close(); }
});

test('toggle preserves granularity and granularity survives off/on', async () => {
  const seen = [];
  const t = await open(() => moves, { onGranularity: (g) => seen.push(g) });
  try {
    setMoveGranularity('sentence')(t.view.state, t.view.dispatch);
    toggleMoveOverlay(t.view.state, t.view.dispatch);
    assert.equal(isMoveOverlayOn(t.view.state), false);
    assert.equal(selectedMoveGranularity(t.view.state), 'sentence');
    assert.equal(decos(t.view.state).length, 0);
    toggleMoveOverlay(t.view.state, t.view.dispatch);
    assert.equal(selectedMoveGranularity(t.view.state), 'sentence');
    assert.equal(decos(t.view.state).length, moves.filter((e) => e.level === 'sentence').length);
    assert.deepEqual(seen, ['sentence']);
  } finally { await t.close(); }
});

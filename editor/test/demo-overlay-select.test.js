// RE-10 (demo): the overlay select chooses one overlay at a time (moves default); only the selected
// overlay's sidecar entries decorate. Synthetic, LLM-built samples only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { OVERLAYS, DEFAULT_OVERLAY } = await import('../src/decorations.js');
const { moveOverlayPlugin, moveOverlayKey, moveDecorations, setMoveOverlaySelection, selectedMoveOverlaySelection,
  setMoveGranularity, toggleMoveOverlay } = await import('../demo/overlay.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const name = 'synthetic-sample-3.md';
const source = readFileSync(join(dir, name), 'utf8');
const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const overlayOf = (e) => e.overlay ?? 'moves';
const levelOf = (e) => e.level ?? 'paragraph';

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
const want = (overlay, level = 'paragraph') => moves.filter((e) => overlayOf(e) === overlay && levelOf(e) === level);

test('sample 3 sidecar carries non-moves entries', () => {
  const others = moves.filter((e) => overlayOf(e) !== 'moves');
  assert.ok(others.length >= 2);
  for (const e of others) {
    assert.ok(OVERLAYS.includes(e.overlay));
    assert.match(e.kind, /^[a-z][a-z0-9-]*$/);
  }
});

test('default overlay is moves and decorates only moves entries', async () => {
  const t = await open();
  try {
    assert.equal(selectedMoveOverlaySelection(t.view.state), DEFAULT_OVERLAY);
    const got = decos(t.view.state);
    assert.equal(got.length, want('moves').length);
    for (const d of got) assert.equal(d.type.attrs['data-signal-overlay'], 'moves');
  } finally { await t.close(); }
});

test('switching overlay filters decorations; meta-only; kind attrs', async () => {
  const t = await open();
  try {
    const before = JSON.stringify(t.view.state.doc.toJSON());
    let steps = -1;
    assert.equal(setMoveOverlaySelection('register')(t.view.state, (tr) => { steps = tr.steps.length; t.view.dispatch(tr); }), true);
    assert.equal(steps, 0);
    assert.equal(JSON.stringify(t.view.state.doc.toJSON()), before);
    assert.equal(selectedMoveOverlaySelection(t.view.state), 'register');
    const expected = want('register');
    assert.ok(expected.length > 0);
    const got = decos(t.view.state);
    assert.equal(got.length, expected.length);
    for (const d of got) {
      assert.equal(d.type.attrs['data-signal-overlay'], 'register');
      assert.ok(expected.some((e) => e.kind === d.type.attrs['data-signal-kind']));
      assert.equal(d.type.attrs['data-move'], undefined);
      assert.equal(d.type.attrs.style, undefined);
    }
    assert.equal(t.root.querySelectorAll('[data-signal-overlay="register"]').length, expected.length);
    setMoveOverlaySelection('topic')(t.view.state, t.view.dispatch);
    assert.equal(decos(t.view.state).length, want('topic').length);
  } finally { await t.close(); }
});

test('unknown overlay throws; sidecar overlay validated', () => {
  assert.throws(() => setMoveOverlaySelection('colour'), /overlay/);
  assert.throws(() => moveOverlayPlugin(() => [], () => genre, { initialOverlay: 'nope' }), /overlay/);
});

test('non-moves entry kind is a slug; moves entry still genre-validated', async () => {
  const t = await open();
  try {
    const doc = t.view.state.doc;
    assert.throws(() => moveDecorations(doc, [{ block: 0, overlay: 'nope', kind: 'x' }], genre), /overlay/);
    assert.throws(() => moveDecorations(doc, [{ block: 0, overlay: 'register', kind: 'Bad Kind' }], genre), /kind/);
    assert.throws(() => moveDecorations(doc, [{ block: 0, move: 'not-in-genre' }], genre), /genre/);
    assert.equal(moveDecorations(doc, [{ block: 0, overlay: 'register', kind: 'not-in-genre' }], genre, 'paragraph', 'register').find().length, 1);
  } finally { await t.close(); }
});

test('selection survives toggle, granularity change and plugin re-creation (sample switch)', async () => {
  const t = await open();
  try {
    setMoveOverlaySelection('support')(t.view.state, t.view.dispatch);
    toggleMoveOverlay(t.view.state, t.view.dispatch);
    assert.equal(decos(t.view.state).length, 0);
    toggleMoveOverlay(t.view.state, t.view.dispatch);
    assert.equal(selectedMoveOverlaySelection(t.view.state), 'support');
    setMoveGranularity('section')(t.view.state, t.view.dispatch);
    setMoveGranularity('paragraph')(t.view.state, t.view.dispatch);
    assert.equal(selectedMoveOverlaySelection(t.view.state), 'support');
    assert.equal(decos(t.view.state).length, want('support').length);
  } finally { await t.close(); }
  let seen = null;
  const t2 = await open(() => moves, { initialOverlay: 'support', onOverlay: (n) => { seen = n; } });
  try {
    assert.equal(selectedMoveOverlaySelection(t2.view.state), 'support');
    assert.equal(decos(t2.view.state).length, want('support').length);
    setMoveOverlaySelection('redundancy')(t2.view.state, t2.view.dispatch);
    assert.equal(seen, 'redundancy');
    assert.equal(decos(t2.view.state).length, want('redundancy').length);
  } finally { await t2.close(); }
});

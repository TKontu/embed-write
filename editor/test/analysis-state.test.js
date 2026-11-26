// IA-02: analysis results live in plugin state (setSignals); applying them never changes the document.
// LLM-built synthetic document and signals only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { setupDom } from './dom.js';

setupDom();
const { signalDecorationsPlugin, signalOverlayKey, setSignals, toggleSignalOverlay, setSignalOverlay,
  setSignalGranularity, isSignalOverlayOn, selectedSignalOverlay, selectedSignalGranularity } =
  await import('../src/decorations.js');
const { EditorState } = await import('@milkdown/prose/state');
const { parseMarkdown, serializeMarkdown, assignIds } = await import('docmodel');

const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n\n## Sub\n\nThird para.\n'));
const ids = [];
doc.descendants((n) => { if (n.attrs.id) ids.push(n.attrs.id); });
const sig = (node_id, over = {}) => ({ node_id, level: 'paragraph', kind: 'readability', value: 1,
  confidence: 0.5, method_ref: 'm@1', layer: 'provisional', ...over });
const hash = (d) => createHash('sha256').update(JSON.stringify(d.toJSON())).digest('hex');
const mdHash = (d) => createHash('sha256').update(serializeMarkdown(d)).digest('hex');

const fresh = (getSignals = () => [], opts) =>
  EditorState.create({ doc, plugins: [signalDecorationsPlugin(getSignals, opts)] });
const run = (state, cmd) => {
  let tr = null;
  const ok = cmd(state, (t) => { tr = t; });
  assert.equal(ok, true);
  return { tr, state: state.apply(tr) };
};
const decos = (state) => {
  const plugin = state.plugins.find((p) => p.spec.key === signalOverlayKey);
  return plugin.props.decorations.call(plugin, state).find();
};
const kinds = (state) => decos(state).map((d) => `${d.from}:${d.type.attrs['data-signal-kind']}`).sort();

test('(a) setSignals carries no steps and leaves the document hash unchanged', () => {
  const h0 = hash(doc);
  const m0 = mdHash(doc);
  const sets = [[], [sig(ids[1])], [sig('UNKNOWN-1'), sig('UNKNOWN-2')],
    ids.map((id, i) => sig(id, { layer: i % 2 ? 'confirmed' : 'provisional', confidence: i / 10 })),
    [sig(ids[2], { overlay: 'register', level: 'sentence' })]];
  let state = fresh();
  for (const s of sets) {
    const r = run(state, setSignals(s));
    assert.equal(r.tr.docChanged, false);
    assert.equal(r.tr.steps.length, 0);
    state = r.state;
    assert.equal(hash(state.doc), h0);
    assert.equal(mdHash(state.doc), m0);
    assert.ok(state.doc.eq(doc));
  }
});

test('(b) decorations come from stored signals and replace earlier ones; stored beat getSignals', () => {
  let state = fresh(() => [sig(ids[0], { kind: 'from-getter' })]);
  assert.deepEqual(decos(state).map((d) => d.type.attrs['data-signal-kind']), ['from-getter']);
  state = run(state, setSignals([sig(ids[1], { kind: 'a' }), sig(ids[2], { kind: 'b' })])).state;
  assert.deepEqual(decos(state).map((d) => d.type.attrs['data-signal-kind']).sort(), ['a', 'b']);
  state = run(state, setSignals([sig(ids[3], { kind: 'c' })])).state;
  assert.deepEqual(decos(state).map((d) => d.type.attrs['data-signal-kind']), ['c']);
  state = run(state, setSignals([])).state;
  assert.equal(decos(state).length, 0);
});

test('(b) stored signals are copied: later mutation of the caller array does not leak in', () => {
  const arr = [sig(ids[1])];
  let state = run(fresh(), setSignals(arr)).state;
  arr.push(sig(ids[2]));
  assert.equal(decos(state).length, 1);
});

test('(c) setSignals preserves on/off, overlay and granularity', () => {
  let state = fresh(() => [], { initiallyOn: false, initialOverlay: 'topic', initialGranularity: 'section' });
  state = run(state, setSignals([sig(ids[1], { overlay: 'topic', level: 'section' })])).state;
  assert.equal(isSignalOverlayOn(state), false);
  assert.equal(selectedSignalOverlay(state), 'topic');
  assert.equal(selectedSignalGranularity(state), 'section');
  assert.equal(decos(state).length, 0); // off
});

test('(c) toggle, overlay and granularity commands preserve stored signals', () => {
  let state = run(fresh(() => [sig(ids[0], { kind: 'getter' })]),
    setSignals([sig(ids[1], { kind: 'stored', overlay: 'register', level: 'sentence' })])).state;
  state = run(state, toggleSignalOverlay).state;
  assert.equal(decos(state).length, 0);
  state = run(state, toggleSignalOverlay).state;
  state = run(state, setSignalOverlay('register')).state;
  state = run(state, setSignalGranularity('sentence')).state;
  assert.deepEqual(decos(state).map((d) => d.type.attrs['data-signal-kind']), ['stored']);
  assert.deepEqual(signalOverlayKey.getState(state).signals.map((s) => s.kind), ['stored']);
});

test('(c) document edits keep stored signals', () => {
  let state = run(fresh(), setSignals([sig(ids[1], { kind: 'kept' })])).state;
  state = state.apply(state.tr.insertText('x', 3));
  assert.deepEqual(signalOverlayKey.getState(state).signals.map((s) => s.kind), ['kept']);
});

test('(d) invalid signals throw at setSignals time and dispatch nothing', () => {
  const bad = [[sig(ids[1], { layer: 'final' })], [sig(ids[1], { confidence: 1.5 })],
    [sig(ids[1], { confidence: NaN })], [sig(ids[1], { confidence: '0.5' })],
    [sig(ids[1], { overlay: 'nope' })], [sig(ids[1], { level: 'word' })], [sig('UNKNOWN', { layer: 'x' })], 'notarray'];
  for (const s of bad) {
    let dispatched = 0;
    assert.throws(() => setSignals(/** @type {any} */ (s))(fresh(), () => { dispatched++; }), JSON.stringify(s));
    assert.equal(dispatched, 0);
  }
});

test('setSignals without the plugin returns false', () => {
  const state = EditorState.create({ doc });
  assert.equal(setSignals([])(state, () => assert.fail('dispatched')), false);
});

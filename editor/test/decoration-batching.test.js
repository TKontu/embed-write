// FP-01: overlay DecorationSet kept in plugin state, mapped through edits, rebuilt only on overlay meta.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { signalDecorationsPlugin, signalOverlayKey, updateSignalOverlay, setSignalOverlay } = await import('../src/index.js');
const { EditorState } = await import('@milkdown/prose/state');
const { parseMarkdown, assignIds } = await import('docmodel');

// LLM-built synthetic document.
const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n'));
const nodes = [];
doc.descendants((n, pos) => { if (n.attrs.id) nodes.push({ id: n.attrs.id, pos, size: n.nodeSize }); });
const sig = (node_id, extra = {}) => ({ node_id, level: 'paragraph', kind: 'k', confidence: 0.9, layer: 'provisional', ...extra });

const setup = () => {
  let calls = 0;
  const plugin = signalDecorationsPlugin(() => { calls += 1; return [sig(nodes[2].id)]; });
  const state = EditorState.create({ doc, plugins: [plugin] });
  return { plugin, state, calls: () => calls };
};

test('doc-only edit maps decorations without calling getSignals', () => {
  const { plugin, state, calls } = setup();
  assert.equal(calls(), 1); // init
  const [before] = plugin.props.decorations(state).find();
  assert.equal(before.from, nodes[2].pos);
  const next = state.apply(state.tr.insertText('XYZ', 1)); // insertion before the signal's node
  for (let i = 0; i < 3; i += 1) plugin.props.decorations(next);
  assert.equal(calls(), 1);
  const found = plugin.props.decorations(next).find();
  assert.equal(found.length, 1);
  assert.equal(found[0].from, nodes[2].pos + 3);
  assert.equal(found[0].to, nodes[2].pos + nodes[2].size + 3);
  assert.equal(next.doc.nodeAt(found[0].from).attrs.id, nodes[2].id);
});

test('overlay meta transaction rebuilds', () => {
  const { state, calls } = setup();
  let next = null;
  setSignalOverlay('register')(state, (tr) => { next = state.apply(tr); });
  assert.equal(calls(), 2);
  assert.equal(signalOverlayKey.getState(next).decorations.find().length, 0);
});

test('updateSignalOverlay applies overlay, granularity and signals in one transaction', () => {
  const { plugin, state } = setup();
  const trs = [];
  const ok = updateSignalOverlay({ overlay: 'support', granularity: 'sentence',
    signals: [sig(nodes[1].id, { overlay: 'support', level: 'sentence' })] })(state, (tr) => trs.push(tr));
  assert.equal(ok, true);
  assert.equal(trs.length, 1);
  const next = state.apply(trs[0]);
  const s = signalOverlayKey.getState(next);
  assert.equal(s.overlay, 'support');
  assert.equal(s.granularity, 'sentence');
  assert.equal(s.signals.length, 1);
  const found = plugin.props.decorations(next).find();
  assert.equal(found.length, 1);
  assert.equal(found[0].from, nodes[1].pos);
});

test('invalid patch throws before dispatch', () => {
  for (const bad of [{ overlay: 'nope' }, { granularity: 'word' }, { on: 'yes' }, { signals: 'x' },
    { signals: [sig('a', { confidence: 2 })] }, { colour: 'red' }, null]) {
    assert.throws(() => updateSignalOverlay(/** @type {any} */ (bad)));
  }
});

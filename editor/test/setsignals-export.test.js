// IA-02b: setSignals is part of the editor package's public surface (src/index.js).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { setSignals, signalDecorationsPlugin, signalOverlayKey } = await import('../src/index.js');
const { EditorState } = await import('@milkdown/prose/state');
const { parseMarkdown, assignIds } = await import('docmodel');

// LLM-built synthetic document.
const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n'));
const ids = [];
doc.descendants((n) => { if (n.attrs.id) ids.push(n.attrs.id); });
const sig = (node_id) => ({ node_id, level: 'paragraph', kind: 'readability', value: 1,
  confidence: 0.5, method_ref: 'm@1', layer: 'provisional' });

test('setSignals imported from index.js stores signals that drive decorations without changing the doc', () => {
  assert.equal(typeof setSignals, 'function');
  const plugin = signalDecorationsPlugin(() => []);
  const state = EditorState.create({ doc, plugins: [plugin] });
  assert.equal(plugin.props.decorations(state).find().length, 0);
  let next = null;
  assert.equal(setSignals([sig(ids[1]), sig(ids[2])])(state, (tr) => { next = state.apply(tr); }), true);
  assert.ok(next);
  assert.ok(next.doc.eq(state.doc));
  assert.equal(signalOverlayKey.getState(next).signals.length, 2);
  const found = plugin.props.decorations(next).find();
  assert.equal(found.length, 2);
});

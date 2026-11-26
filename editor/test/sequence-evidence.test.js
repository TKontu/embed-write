// IN-02 (D-009 slice): the inspector shows sequence evidence for a move mark — sample support for
// (previous move -> this move) over the synthetic, LLM-built demo samples. Pattern fit, not a verdict.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { moveOverlayPlugin } = await import('../demo/overlay.js');
const { blockEvidence, moveSequence, previousMove, sequenceEvidence, transitionStats } =
  await import('../src/comparison.js');
const { mountInspector, renderInspector } = await import('../src/inspector.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const sampleNames = [1, 2, 3].map((i) => `synthetic-sample-${i}`);
const sampleMoves = sampleNames.map((n) => JSON.parse(readFileSync(join(dir, `${n}.moves.json`), 'utf8')));

const info = { signal: 'Move', value: 'Finding', confidence: '1', layer: 'provisional',
  methodId: 'finding', methodText: 'x' };

test('(a) transitionStats counts each transition once per sample', () => {
  const s = transitionStats([['a', 'b', 'a', 'b'], ['a', 'c'], []]);
  assert.equal(s.samples, 2);
  assert.equal(s.firsts.get('a'), 2);
  assert.equal(s.contains.get('a'), 2);
  assert.equal(s.contains.get('b'), 1);
  assert.equal(s.trans.get('a').get('b'), 1);
  assert.equal(s.trans.get('b').get('a'), 1);
  assert.equal(s.trans.get('a').get('c'), 1);
});

test('(b) sequenceEvidence: follows, opens and zero cases', () => {
  const s = transitionStats([['a', 'b'], ['a', 'c'], ['b', 'a']]);
  assert.deepEqual(sequenceEvidence(s, 'a', 'b'), { from: 'a', to: 'b', count: 1, of: 3 });
  assert.deepEqual(sequenceEvidence(s, null, 'a'), { from: null, to: 'a', count: 2, of: 3 });
  assert.deepEqual(sequenceEvidence(s, 'c', 'a'), { from: 'c', to: 'a', count: 0, of: 1 });
  assert.equal(previousMove([{ block: 0, move: 'a' }, { block: 1, move: 'a' }, { block: 3, move: 'b' }], 3), 'a');
  assert.equal(previousMove([{ block: 0, move: 'a' }, { block: 1, move: 'a' }], 1), null);
  assert.equal(previousMove([{ block: 0, move: 'a' }], 2), undefined);
});

test('(d) renderInspector with evidence shows sentence and labels; without, as before', () => {
  const plain = renderInspector(document, info);
  assert.equal(plain.querySelector('.inspector-evidence'), null);
  assert.equal(renderInspector(document, info, null).outerHTML, plain.outerHTML);
  const cases = [
    [{ from: 'method', to: 'finding', count: 2, of: 3, fromName: 'Method', toName: 'Finding' },
      'Finding follows Method in 2 of 3 samples'],
    [{ from: null, to: 'finding', count: 1, of: 3, toName: 'Finding' }, 'Finding opens the report in 1 of 3 samples'],
    [{ from: 'method', to: 'finding', count: 0, of: 3, fromName: 'Method', toName: 'Finding' },
      'No sample has Finding after Method'],
  ];
  for (const [ev, text] of cases) {
    const el = renderInspector(document, info, ev);
    assert.equal(el.querySelector('.inspector-evidence-text').textContent, text);
    assert.match(el.textContent, /synthetic samples, LLM-built/);
    assert.match(el.querySelector('.inspector-evidence').textContent, /Pattern fit, not a verdict/);
  }
});

test('(e) demo wiring: hovered move mark shows evidence text in the inspector', async () => {
  const name = 'synthetic-sample-1';
  const moves = sampleMoves[0];
  const stats = transitionStats(sampleMoves.map(moveSequence));
  const root = document.body.appendChild(document.createElement('div'));
  const mount = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: readFileSync(join(dir, `${name}.md`), 'utf8') });
  try {
    const view = editor.view;
    // Same wiring as editor/demo/app.js evidenceFor().
    const inspector = mountInspector(view.dom, mount, () => genre, (el) =>
      blockEvidence(stats, moves, view.state.doc.resolve(view.posAtDOM(el, 0)).index(0), genre));
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins,
      moveOverlayPlugin(() => moves, () => genre)] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    const marks = [...root.querySelectorAll('[data-signal-kind]')];
    const later = marks.find((m) => m.getAttribute('data-signal-kind') !== marks[0].getAttribute('data-signal-kind'));
    assert.ok(later);
    later.dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    const block = view.state.doc.resolve(view.posAtDOM(later, 0)).index(0);
    const ev = sequenceEvidence(stats, previousMove(moves, block), moves.find((e) => e.block === block).move);
    const text = mount.querySelector('.inspector-evidence-text')?.textContent ?? '';
    assert.match(text, new RegExp(`in ${ev.count} of ${ev.of} samples|No sample has`), mount.textContent);
    assert.match(mount.textContent, /synthetic samples, LLM-built/);
    marks[0].dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    assert.match(mount.querySelector('.inspector-evidence-text').textContent, /opens the report in \d+ of 3 samples/);
    inspector.destroy();
  } finally {
    await editor.destroy();
    root.remove();
    mount.remove();
  }
});

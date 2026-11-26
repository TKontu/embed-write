// IN-03 (D-009 slice): the inspector shows candidate evidence for a support flag, from the
// synthetic, LLM-built examples/demo/*.support.json. No support model. Pattern fit, not a verdict.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { moveOverlayPlugin } = await import('../demo/overlay.js');
const { mountInspector, renderInspector, renderSupportEvidence, supportEvidence } =
  await import('../src/inspector.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const info = { signal: 'Move', value: 'Finding', confidence: '1', layer: 'provisional',
  methodId: 'finding', methodText: 'x' };

test('(a) supportEvidence: null, sorted, empty, malformed', () => {
  const flags = [
    { block: 3, candidates: [{ block: 5, score: 0.2 }, { block: 2, score: 0.9 }, { block: 1, score: 0.2 }] },
    { block: 4, candidates: [] },
  ];
  assert.equal(supportEvidence(flags, 0), null);
  assert.deepEqual(supportEvidence(flags, 3), { block: 3, candidates: [
    { block: 2, score: 0.9 }, { block: 1, score: 0.2 }, { block: 5, score: 0.2 }] });
  assert.deepEqual(supportEvidence(flags, 4), { block: 4, candidates: [] });
  assert.deepEqual(flags[0].candidates[0], { block: 5, score: 0.2 }, 'input not mutated');
  for (const bad of [null, {}, [{ block: -1, candidates: [] }], [{ block: 1 }], [{ block: 1.5, candidates: [] }],
    [{ block: 1, candidates: [{ block: 2, score: 1.5 }] }], [{ block: 1, candidates: [{ block: 2 }] }],
    [{ block: 1, candidates: [null] }], [{ block: 1, candidates: [{ block: 'x', score: 0.1 }] }]]) {
    assert.throws(() => supportEvidence(bad, 1), TypeError, JSON.stringify(bad));
  }
  for (const i of [1, 2, 3]) {
    const f = JSON.parse(readFileSync(join(dir, `synthetic-sample-${i}.support.json`), 'utf8'));
    for (const flag of f) assert.ok(supportEvidence(f, flag.block));
  }
});

test('(b) renderSupportEvidence: candidates with excerpt and score, or none found; labels', () => {
  const ex = (/** @type {number} */ b) => `text of ${b}`;
  const el = renderSupportEvidence(document, { block: 3, candidates: [{ block: 2, score: 0.9 }, { block: 5, score: 0.25 }] }, ex);
  const items = [...el.querySelectorAll('.inspector-support-candidate')].map((li) => li.textContent);
  assert.deepEqual(items, ['Block 2: "text of 2" (score 0.90)', 'Block 5: "text of 5" (score 0.25)']);
  assert.equal(el.querySelector('.inspector-support-none'), null);
  assert.match(el.textContent, /Candidate evidence \(synthetic support flags, LLM-built\)/);
  assert.match(el.textContent, /Pattern fit, not a verdict/);
  const none = renderSupportEvidence(document, { block: 4, candidates: [] }, ex);
  assert.equal(none.querySelector('.inspector-support-none').textContent, 'No candidate evidence found');
  assert.match(none.textContent, /synthetic support flags, LLM-built/);
  assert.match(none.textContent, /Pattern fit, not a verdict/);
});

test('(c) renderInspector without support renders as before', () => {
  const plain = renderInspector(document, info);
  assert.equal(renderInspector(document, info, null, null).outerHTML, plain.outerHTML);
  assert.equal(plain.querySelector('.inspector-support'), null);
});

test('(d) demo wiring: flagged block shows candidates, other shows none found', async () => {
  const name = 'synthetic-sample-1';
  const moves = JSON.parse(readFileSync(join(dir, `${name}.moves.json`), 'utf8'));
  const flags = JSON.parse(readFileSync(join(dir, `${name}.support.json`), 'utf8'));
  const root = document.body.appendChild(document.createElement('div'));
  const mount = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: readFileSync(join(dir, `${name}.md`), 'utf8') });
  try {
    const view = editor.view;
    const blockOf = (/** @type {Element} */ el) => view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    // Same wiring as editor/demo/app.js supportFor().
    const inspector = mountInspector(view.dom, mount, () => genre, undefined, (el) => {
      const evidence = supportEvidence(flags, blockOf(el));
      return evidence ? { evidence, excerptOf: (b) => view.state.doc.child(b).textContent.slice(0, 60) } : null;
    });
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins,
      moveOverlayPlugin(() => moves, () => genre)] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    const marks = [...root.querySelectorAll('[data-signal-kind]')];
    const at = (/** @type {number} */ b) => marks.find((m) => blockOf(m) === b);
    at(8).dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    const items = [...mount.querySelectorAll('.inspector-support-candidate')];
    assert.deepEqual(items.map((li) => li.dataset.block), ['6', '7']);
    assert.match(items[0].textContent, /^Block 6: ".+" \(score 0\.71\)$/);
    assert.match(mount.textContent, /synthetic support flags, LLM-built/);
    at(9).dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    assert.equal(mount.querySelector('.inspector-support-none').textContent, 'No candidate evidence found');
    at(0).dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    assert.equal(mount.querySelector('.inspector-support'), null);
    inspector.destroy();
  } finally {
    await editor.destroy();
    root.remove();
    mount.remove();
  }
});

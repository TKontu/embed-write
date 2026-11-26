// IN-05 (D-009 slice): expert label correction from the inspector. Synthetic samples only; the
// store is a temp dir. Precedence mirrors analysis/label_precedence.py (DS-02).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { moveOverlayPlugin } = await import('../demo/overlay.js');
const { startServer } = await import('../demo/server.js');
const { mountInspector, renderCorrectionControl } = await import('../src/inspector.js');
const { resolveMoveLabel, applyCorrections, addCorrection, EXPERT_LAYER } = await import('../src/corrections.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const nameOf = (id) => genre.moves.find((m) => m.id === id)?.name ?? id;

test('(a) resolveMoveLabel: expert > slow_layer > fast in any order; latest timestamp; throws', () => {
  const fast = { block: 1, label: 'context', source: 'fast' };
  const slow = { block: 1, label: 'gap', source: 'slow_layer', timestamp: 5 };
  const expert = { block: 1, label: 'finding', source: 'expert', timestamp: 1 };
  for (const order of [[fast, slow, expert], [expert, slow, fast], [slow, expert, fast]]) {
    assert.equal(resolveMoveLabel(order), expert);
  }
  assert.equal(resolveMoveLabel([slow, fast]), slow);
  assert.equal(resolveMoveLabel([fast, slow]), slow);
  assert.equal(resolveMoveLabel([]), null);
  const e2 = { ...expert, label: 'method', timestamp: 9 };
  assert.equal(resolveMoveLabel([e2, expert]), e2);
  const noTs = { block: 1, label: 'gap', source: 'expert' };
  assert.equal(resolveMoveLabel([expert, noTs]), expert);
  const tie = { ...expert, label: 'gap' };
  assert.equal(resolveMoveLabel([expert, tie]), tie);
  for (const bad of [[{ ...fast, source: 'model' }], [{ label: 'x', source: 'fast' }],
    [{ block: 1, source: 'fast' }], [null], [fast, { ...fast, block: 2 }]]) {
    assert.throws(() => resolveMoveLabel(bad), TypeError, JSON.stringify(bad));
  }
});

test('(b) applyCorrections changes only corrected blocks and marks the layer', () => {
  const entries = [{ block: 0, move: 'context' }, { block: 1, move: 'context' }, { block: 2, move: 'gap' }];
  const corr = [{ block: 1, label: 'gap', previous: 'context', source: 'expert', timestamp: 1 },
    { block: 1, label: 'finding', previous: 'context', source: 'expert', timestamp: 2 },
    { block: 7, label: 'gap', previous: null, source: 'expert', timestamp: 3 }];
  const out = applyCorrections(entries, corr);
  assert.deepEqual(out, [{ block: 0, move: 'context', layer: 'provisional' },
    { block: 1, move: 'finding', layer: EXPERT_LAYER, previous: 'context' },
    { block: 2, move: 'gap', layer: 'provisional' }]);
  assert.equal(entries[1].move, 'context');
  assert.throws(() => applyCorrections(entries, [{ block: 1, label: 'gap', source: 'fast', timestamp: 1, previous: null }]), TypeError);
  assert.deepEqual(addCorrection([], entries, 2, 'finding', 7),
    [{ block: 2, label: 'finding', previous: 'gap', source: 'expert', timestamp: 7 }]);
});

test('(c) renderCorrectionControl lists genre moves, preselects current, calls onSave', () => {
  const saved = [];
  const el = renderCorrectionControl(document, { moves: genre.moves, current: 'gap', onSave: (id) => saved.push(id) });
  const select = el.querySelector('select');
  assert.equal(el.querySelector('label').textContent.startsWith('Correct label'), true);
  assert.deepEqual([...select.options].map((o) => o.value), genre.moves.map((m) => m.id));
  assert.equal(select.value, 'gap');
  select.value = 'finding';
  el.querySelector('button').click();
  assert.deepEqual(saved, ['finding']);
});

async function withEditor(name, fn) {
  const root = document.body.appendChild(document.createElement('div'));
  const mount = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: readFileSync(join(dir, `${name}.md`), 'utf8') });
  try { await fn(editor.view, root, mount); } finally {
    await editor.destroy();
    root.remove();
    mount.remove();
  }
}

test('(d) mountInspector without onCorrect has no correction control', async () => {
  const moves = JSON.parse(readFileSync(join(dir, 'synthetic-sample-1.moves.json'), 'utf8'));
  await withEditor('synthetic-sample-1', async (view, root, mount) => {
    const inspector = mountInspector(view.dom, mount, () => genre);
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins, moveOverlayPlugin(() => moves, () => genre)] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    root.querySelector('[data-signal-kind]').dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    assert.ok(mount.querySelector('.inspector dl'));
    assert.equal(mount.querySelector('.inspector-correct'), null);
    assert.equal(mount.querySelector('.inspector-corrected'), null);
    assert.equal(mount.querySelector('[data-field="layer"]').textContent, 'provisional');
    inspector.destroy();
  });
});

test('(e) /api/corrections round-trips in the configured dir and refuses bad input', async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'demo-corr-samples-'));
  const store = mkdtempSync(join(tmpdir(), 'demo-corr-store-'));
  writeFileSync(join(tmp, 'a.md'), '# A\n');
  const run = await startServer({ dir: tmp, port: 0, correctionsDir: join(store, 'nested') });
  const url = (p) => new URL(p, run.url);
  const put = (p, body, headers = {}) => fetch(url(p), { method: 'PUT', headers: { 'content-type': 'application/json', ...headers }, body });
  try {
    assert.deepEqual(await (await fetch(url('api/corrections/a.md'))).json(), []);
    const list = [{ block: 0, label: 'finding', previous: null, source: 'expert', timestamp: 1 }];
    const ok = await put('api/corrections/a.md', JSON.stringify(list));
    assert.equal(ok.status, 200);
    assert.deepEqual(await (await fetch(url('api/corrections/a.md'))).json(), list);
    assert.ok(existsSync(join(store, 'nested', 'a.corrections.json')));
    assert.deepEqual(readdirSync(tmp), ['a.md']);
    assert.equal((await put('api/corrections/a.md', JSON.stringify([{ ...list[0], label: 'nope' }]))).status, 400);
    assert.equal((await put('api/corrections/a.md', '{not json')).status, 400);
    assert.equal((await put('api/corrections/a.md', '{"block":0}')).status, 400);
    assert.equal((await put('api/corrections/a.md', JSON.stringify([{ ...list[0], source: 'fast' }]))).status, 400);
    for (const attempt of ['..%2Fsecret.md', '%2e%2e%2fsecret.md', '%2Fetc%2Fpasswd.md']) {
      const got = await put(`api/corrections/${attempt}`, JSON.stringify(list));
      assert.ok([400, 404].includes(got.status), `${attempt} -> ${got.status}`);
    }
    const foreign = await put('api/corrections/a.md', JSON.stringify(list), { origin: 'http://evil.example' });
    assert.equal(foreign.status, 403);
    assert.deepEqual(await (await fetch(url('api/corrections/a.md'))).json(), list);
  } finally {
    await run.close();
    rmSync(tmp, { recursive: true, force: true });
    rmSync(store, { recursive: true, force: true });
  }
});

test('(f) demo wiring: correcting a block relabels the mark and the inspector says so', async () => {
  const name = 'synthetic-sample-1';
  const sidecar = JSON.parse(readFileSync(join(dir, `${name}.moves.json`), 'utf8'));
  await withEditor(name, async (view, root, mount) => {
    let corrections = [];
    let moves = applyCorrections(sidecar, corrections);
    const blockOf = (el) => view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    // Same wiring as editor/demo/app.js correctLabel() (minus the PUT).
    const inspector = mountInspector(view.dom, mount, () => genre, undefined, undefined, undefined,
      (el, label) => {
        corrections = addCorrection(corrections, sidecar, blockOf(el), label, 1);
        moves = applyCorrections(sidecar, corrections);
        view.dispatch(view.state.tr.setMeta('demo:corrected', true));
      });
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins, moveOverlayPlugin(() => moves, () => genre)] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    const markAt = (b) => [...root.querySelectorAll('[data-signal-kind]')].find((m) => blockOf(m) === b);
    const hover = (b) => markAt(b).dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    hover(0);
    assert.equal(markAt(0).getAttribute('data-move'), 'context');
    const select = mount.querySelector('.inspector-correct-select');
    assert.equal(select.value, 'context');
    select.value = 'finding';
    mount.querySelector('.inspector-correct-save').click();
    assert.equal(markAt(0).getAttribute('data-move'), 'finding');
    assert.equal(markAt(0).getAttribute('data-signal-layer'), EXPERT_LAYER);
    assert.equal(markAt(1).getAttribute('data-move'), 'context');
    hover(0);
    assert.equal(mount.querySelector('[data-field="layer"]').textContent, EXPERT_LAYER);
    assert.equal(mount.querySelector('[data-field="value"]').textContent, nameOf('finding'));
    assert.equal(mount.querySelector('.inspector-corrected').textContent, `Corrected by expert (was ${nameOf('context')})`);
    hover(1);
    assert.equal(mount.querySelector('.inspector-corrected'), null);
    inspector.destroy();
  });
});

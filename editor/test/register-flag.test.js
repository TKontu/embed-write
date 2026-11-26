// IN-04 (D-009 slice): the inspector names the off-register feature for a register flag, from the
// synthetic, LLM-built examples/demo/*.register.json. No register model. Pattern fit, not a verdict.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { moveOverlayPlugin } = await import('../demo/overlay.js');
const { startServer } = await import('../demo/server.js');
const { mountInspector, renderInspector, renderRegisterFlag, registerFlag } =
  await import('../src/inspector.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const info = { signal: 'Move', value: 'Finding', confidence: '1', layer: 'provisional',
  methodId: 'finding', methodText: 'x' };

test('(a) registerFlag: null, flag, malformed, duplicate', () => {
  const flags = [{ block: 3, feature: 'passive voice', note: 'n', distance: 0.5 }, { block: 4, feature: 'hedges' }];
  assert.equal(registerFlag(flags, 0), null);
  assert.deepEqual(registerFlag(flags, 3), { block: 3, feature: 'passive voice', note: 'n', distance: 0.5 });
  assert.deepEqual(registerFlag(flags, 4), { block: 4, feature: 'hedges' });
  assert.equal(registerFlag([], 0), null);
  for (const bad of [null, {}, [null], [{ block: -1, feature: 'x' }], [{ block: 1.5, feature: 'x' }],
    [{ block: 1 }], [{ block: 1, feature: '' }], [{ block: 1, feature: 2 }],
    [{ block: 1, feature: 'x', note: 3 }], [{ block: 1, feature: 'x', distance: 1.5 }],
    [{ block: 1, feature: 'x', distance: '0.2' }], [{ block: 1, feature: 'x' }, { block: 1, feature: 'y' }]]) {
    assert.throws(() => registerFlag(bad, 1), TypeError, JSON.stringify(bad));
  }
  let flagged = 0;
  let empty = 0;
  for (const i of [1, 2, 3]) {
    const f = JSON.parse(readFileSync(join(dir, `synthetic-sample-${i}.register.json`), 'utf8'));
    for (const flag of f) assert.ok(registerFlag(f, flag.block));
    flagged += f.length;
    if (!f.length) empty += 1;
  }
  assert.ok(flagged >= 1 && empty >= 1);
});

test('(b) renderRegisterFlag: feature, optional note/distance, labels', () => {
  const full = renderRegisterFlag(document, { block: 3, feature: 'passive voice', note: 'many', distance: 0.5 });
  assert.equal(full.querySelector('.inspector-register-feature').textContent, 'Feature: passive voice');
  assert.equal(full.querySelector('.inspector-register-detail').textContent, 'Note: many');
  assert.equal(full.querySelector('.inspector-register-distance').textContent, 'Distance: 0.50');
  assert.match(full.textContent, /Register \(synthetic register flags, LLM-built\)/);
  assert.match(full.textContent, /Pattern fit, not a verdict/);
  const bare = renderRegisterFlag(document, { block: 4, feature: 'hedges' });
  assert.equal(bare.querySelector('.inspector-register-detail'), null);
  assert.equal(bare.querySelector('.inspector-register-distance'), null);
  assert.match(bare.textContent, /synthetic register flags, LLM-built/);
  assert.match(bare.textContent, /Pattern fit, not a verdict/);
});

test('(c) renderInspector without register renders as before', () => {
  const plain = renderInspector(document, info);
  assert.equal(renderInspector(document, info, null, null, null).outerHTML, plain.outerHTML);
  assert.equal(plain.querySelector('.inspector-register'), null);
});

test('(d) demo wiring: flagged block shows the feature, unflagged shows nothing', async () => {
  const name = 'synthetic-sample-1';
  const moves = JSON.parse(readFileSync(join(dir, `${name}.moves.json`), 'utf8'));
  const flags = JSON.parse(readFileSync(join(dir, `${name}.register.json`), 'utf8'));
  const root = document.body.appendChild(document.createElement('div'));
  const mount = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: readFileSync(join(dir, `${name}.md`), 'utf8') });
  try {
    const view = editor.view;
    const blockOf = (/** @type {Element} */ el) => view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    // Same wiring as editor/demo/app.js registerFor().
    const inspector = mountInspector(view.dom, mount, () => genre, undefined, undefined,
      (el) => registerFlag(flags, blockOf(el)));
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins,
      moveOverlayPlugin(() => moves, () => genre)] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    const marks = [...root.querySelectorAll('[data-signal-kind]')];
    const at = (/** @type {number} */ b) => marks.find((m) => blockOf(m) === b);
    at(8).dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    assert.equal(mount.querySelector('.inspector-register-feature').textContent, 'Feature: passive voice');
    assert.match(mount.textContent, /synthetic register flags, LLM-built/);
    at(0).dispatchEvent(new window.MouseEvent('mouseover', { bubbles: true }));
    assert.ok(mount.querySelector('.inspector'));
    assert.equal(mount.querySelector('.inspector-register'), null);
    inspector.destroy();
  } finally {
    await editor.destroy();
    root.remove();
    mount.remove();
  }
});

test('(e) /api/register serves the sample file and refuses paths outside the folder', async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'demo-register-'));
  writeFileSync(join(tmp, 'a.md'), '# A\n');
  writeFileSync(join(tmp, 'a.register.json'), '[{"block":0,"feature":"hedges"}]');
  const run = await startServer({ dir: tmp, port: 0 });
  try {
    const ok = await fetch(new URL('api/register/a.md', run.url));
    assert.equal(ok.status, 200);
    assert.deepEqual(await ok.json(), [{ block: 0, feature: 'hedges' }]);
    assert.equal((await fetch(new URL('api/register/b.md', run.url))).status, 404);
    for (const attempt of ['..%2Fsecret.md', '%2e%2e%2fsecret.md', '%2E%2E/secret.md', '%2Fetc%2Fpasswd.md']) {
      const got = await fetch(new URL(`api/register/${attempt}`, run.url));
      assert.ok([400, 404].includes(got.status), `${attempt} -> ${got.status}`);
    }
  } finally {
    await run.close();
    rmSync(tmp, { recursive: true, force: true });
  }
});

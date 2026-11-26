// OV-01/OV-03 refresh on correction (R188/A1). Synthetic fixtures below are LLM-built; examples/demo
// is the shipped synthetic demo.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';
import { startServer } from '../demo/server.js';

setupDom();
const { refreshOverview } = await import('../src/overview.js');
const { addCorrection, applyCorrections } = await import('../src/corrections.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const sidecar = [{ block: 0, move: 'context' }, { block: 1, move: 'context' }, { block: 2, move: 'method' }];

function mounts() {
  const minimapMount = document.createElement('div');
  const issuesMount = document.createElement('div');
  document.body.append(minimapMount, issuesMount);
  return { minimapMount, issuesMount };
}
const segs = (m) => [...m.querySelectorAll('.minimap-segment')].map((s) =>
  `${s.getAttribute('data-signal-kind') ?? 'unlabeled'}:${s.getAttribute('data-start')}+${s.getAttribute('data-count')}`);

test('(a) a correction supplying a missing move removes it from the rendered issues list', () => {
  const { minimapMount, issuesMount } = mounts();
  const opts = { minimapMount, issuesMount, blockCount: 3, genre, onNavigate: () => {} };
  const before = refreshOverview({ ...opts, moves: sidecar });
  assert.ok(before.some((i) => i.moveId === 'gap'));
  const gapText = before.find((i) => i.moveId === 'gap').text;
  assert.ok([...issuesMount.querySelectorAll('li')].some((li) => li.textContent === gapText));

  const corrected = applyCorrections(sidecar, addCorrection([], sidecar, 1, 'gap', 1));
  const after = refreshOverview({ ...opts, moves: corrected });
  assert.ok(!after.some((i) => i.moveId === 'gap'));
  assert.ok(![...issuesMount.querySelectorAll('li')].some((li) => li.textContent === gapText));
  assert.equal(issuesMount.querySelectorAll('ul.issues').length, 1);
});

test('(b) minimap segments follow the correction and the collapsed/expanded state is kept', () => {
  const { minimapMount, issuesMount } = mounts();
  const opts = { minimapMount, issuesMount, blockCount: 3, genre, onNavigate: () => {} };
  refreshOverview({ ...opts, moves: sidecar });
  assert.deepEqual(segs(minimapMount), ['context:0+2', 'method:2+1']);
  minimapMount.querySelector('.minimap-toggle').click();
  assert.equal(minimapMount.dataset.expanded, 'true');

  const corrected = applyCorrections(sidecar, addCorrection([], sidecar, 1, 'gap', 1));
  refreshOverview({ ...opts, moves: corrected });
  assert.deepEqual(segs(minimapMount), ['context:0+1', 'gap:1+1', 'method:2+1']);
  assert.equal(minimapMount.dataset.expanded, 'true');
  assert.equal(minimapMount.querySelector('.minimap').hidden, false);
  assert.equal(minimapMount.querySelector('.minimap-toggle').getAttribute('aria-expanded'), 'true');
});

test('(c) PUT /api/corrections: missing genre.json -> 404 JSON, malformed -> 400 JSON', async () => {
  const tmp = mkdtempSync(join(tmpdir(), 'ov03-genre-'));
  const store = mkdtempSync(join(tmpdir(), 'ov03-store-'));
  writeFileSync(join(tmp, 'a.md'), '# A\n');
  const run = await startServer({ dir: tmp, port: 0, correctionsDir: store, genreFallback: null });
  const list = [{ block: 0, label: 'gap', previous: null, source: 'expert', timestamp: 1 }];
  const put = () => fetch(new URL('api/corrections/a.md', run.url),
    { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(list) });
  try {
    const missing = await put();
    assert.equal(missing.status, 404);
    assert.match(missing.headers.get('content-type'), /json/);
    assert.match((await missing.json()).error, /genre\.json not found/);

    writeFileSync(join(tmp, 'genre.json'), '{not json');
    const bad = await put();
    assert.equal(bad.status, 400);
    assert.match(bad.headers.get('content-type'), /json/);
    assert.match((await bad.json()).error, /genre\.json/);

    writeFileSync(join(tmp, 'genre.json'), JSON.stringify(genre));
    assert.equal((await put()).status, 200);
  } finally {
    await run.close();
    rmSync(tmp, { recursive: true, force: true });
    rmSync(store, { recursive: true, force: true });
  }
});

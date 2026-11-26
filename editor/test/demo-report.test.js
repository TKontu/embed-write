// DE-05: single-report mode serves exactly one real-named Markdown file and its label sidecar,
// saves back to that file through atomicWrite, and refuses every other name.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startServer, REPORT_LEGEND } from '../demo/server.js';

const report = 'Mÿ Report – draft.md';
const source = '# Weekly note\n\nFirst invented paragraph.\n\nSecond invented paragraph stays.\n';
const labels = [{ block: 1, move: 'context' }];

/** @param {string} dir */
function snapshot(dir) {
  return Object.fromEntries(readdirSync(dir).sort().map((n) => [n, readFileSync(join(dir, n), 'utf8')]));
}

test('serves, labels and saves exactly the one report (name with spaces/non-ASCII)', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'demo-report-'));
  const labelDir = mkdtempSync(join(tmpdir(), 'demo-labels-'));
  try {
    writeFileSync(join(dir, report), source);
    writeFileSync(join(dir, 'Other.md'), 'other\n');
    writeFileSync(join(labelDir, 'labels.json'), JSON.stringify(labels));
    const before = snapshot(dir);
    const run = await startServer({ report: join(dir, report), labels: join(labelDir, 'labels.json'), port: 0 });
    try {
      const listing = await (await fetch(new URL('api/samples', run.url))).json();
      assert.deepEqual(listing.samples, [report]);
      const url = new URL(`api/sample/${encodeURIComponent(report)}`, run.url);
      const got = await fetch(url);
      assert.equal(got.status, 200);
      assert.equal(await got.text(), source);
      assert.deepEqual(await (await fetch(new URL(`api/moves/${encodeURIComponent(report)}`, run.url))).json(), labels);

      const edited = source.replace('First invented paragraph.', 'First changed paragraph.');
      const put = await fetch(url, { method: 'PUT', body: edited });
      assert.equal(put.status, 200);
      const after = snapshot(dir);
      assert.deepEqual(Object.keys(after), Object.keys(before), 'no file created in the report folder');
      assert.equal(after['Other.md'], before['Other.md']);
      const a = source.split('\n'), b = after[report].split('\n');
      assert.equal(a.length, b.length);
      assert.deepEqual(a.map((l, i) => (l === b[i] ? -1 : i)).filter((i) => i >= 0), [2]);

      for (const name of ['Other.md', 'synthetic-sample-1.md', '../x.md', '..%2Fx.md']) {
        const r = await fetch(new URL(`api/sample/${encodeURIComponent(name)}`, run.url));
        assert.ok(r.status >= 400 && r.status < 500, `GET ${name} -> ${r.status}`);
        const w = await fetch(new URL(`api/sample/${encodeURIComponent(name)}`, run.url), { method: 'PUT', body: 'x' });
        assert.ok(w.status >= 400 && w.status < 500, `PUT ${name} -> ${w.status}`);
      }
      assert.deepEqual(snapshot(dir), after, 'refused writes changed nothing');

      const page = await (await fetch(run.url)).text();
      assert.doesNotMatch(page, /synthetic/i);
      assert.match(page, /Provisional/);
      assert.ok(page.includes(REPORT_LEGEND));
      const legend = await (await fetch(new URL('api/legend', run.url))).json();
      assert.equal(legend.provisional, true);
    } finally {
      await run.close();
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(labelDir, { recursive: true, force: true });
  }
});

test('without --labels a sidecar beside the report is used; with neither, no labels', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'demo-report-side-'));
  try {
    writeFileSync(join(dir, 'A Report.md'), source);
    writeFileSync(join(dir, 'A Report.moves.json'), JSON.stringify(labels));
    writeFileSync(join(dir, 'Plain.md'), source);
    let run = await startServer({ report: join(dir, 'A Report.md'), port: 0 });
    try {
      const r = await fetch(new URL(`api/moves/${encodeURIComponent('A Report.md')}`, run.url));
      assert.equal(r.status, 200);
      assert.deepEqual(await r.json(), labels);
    } finally { await run.close(); }
    run = await startServer({ report: join(dir, 'Plain.md'), port: 0 });
    try {
      assert.equal(run.report?.labels, null);
      assert.equal((await fetch(new URL('api/moves/Plain.md', run.url))).status, 404);
      assert.equal((await fetch(new URL('api/sample/Plain.md', run.url))).status, 200);
    } finally { await run.close(); }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('report mode keeps the Host/Origin guard', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'demo-report-host-'));
  try {
    writeFileSync(join(dir, 'R.md'), source);
    const run = await startServer({ report: join(dir, 'R.md'), port: 0 });
    try {
      const { request } = await import('node:http');
      const status = await new Promise((done, fail) => {
        const req = request({ host: '127.0.0.1', port: run.port, path: '/api/sample/R.md', method: 'PUT', headers: { origin: 'http://evil.example' } }, (res) => { res.resume(); done(res.statusCode); });
        req.on('error', fail); req.end('x');
      });
      assert.equal(status, 403);
      assert.equal(readFileSync(join(dir, 'R.md'), 'utf8'), source);
      assert.ok(statSync(join(dir, 'R.md')).isFile());
    } finally { await run.close(); }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('legend says synthetic only for the shipped sample folder', async () => {
  const { SYNTHETIC_LEGEND } = await import('../demo/server.js');
  let run = await startServer({ port: 0 });
  try {
    const page = await (await fetch(run.url)).text();
    assert.ok(page.includes(SYNTHETIC_LEGEND));
    assert.ok(page.includes('Provisional labels: synthetic'));
  } finally { await run.close(); }
  const dir = mkdtempSync(join(tmpdir(), 'demo-legend-'));
  try {
    writeFileSync(join(dir, 'S.md'), source);
    run = await startServer({ dir, port: 0 });
    try {
      const page = await (await fetch(run.url)).text();
      assert.ok(page.includes('Provisional labels: unreviewed placeholders'));
      assert.ok(!page.includes(SYNTHETIC_LEGEND));
    } finally { await run.close(); }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('CLI: --labels without --report is a one-line usage error', async () => {
  const { spawnSync } = await import('node:child_process');
  const { fileURLToPath } = await import('node:url');
  const server = fileURLToPath(new URL('../demo/server.js', import.meta.url));
  const out = spawnSync(process.execPath, [server, '--labels', 'x.json', '--port', '0'], { encoding: 'utf8', timeout: 10000 });
  assert.notEqual(out.status, 0);
  assert.notEqual(out.status, null);
  const lines = out.stderr.trim().split('\n');
  assert.equal(lines.length, 1);
  assert.match(lines[0], /--labels needs --report/);
  assert.doesNotMatch(out.stderr, /\n\s+at /);
});

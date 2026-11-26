// DE-02/DE-03: localhost demo server saves one paragraph without touching other lines and
// refuses paths outside the configured sample folder.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { startServer } from '../demo/server.js';

const demoDir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const sample = 'synthetic-sample-1.md';
const source = readFileSync(join(demoDir, sample), 'utf8');

test('GET a sample, PUT a one-paragraph edit, and only that paragraph line changes', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'demo-save-'));
  writeFileSync(join(dir, sample), source);
  const run = await startServer({ dir, port: 0 });
  try {
    const sampleUrl = new URL(`api/sample/${sample}`, run.url);
    const got = await fetch(sampleUrl);
    assert.equal(got.status, 200);
    assert.equal(await got.text(), source);

    const listing = await (await fetch(new URL('api/samples', run.url))).json();
    assert.deepEqual(listing.samples, [sample]);

    // A real report folder may have no legend; the demo's provisional legend is the fallback.
    const legend = await (await fetch(new URL('api/legend', run.url))).json();
    assert.equal(legend.provisional, true);

    const oldLine = 'A team keeps a short weekly report. The *content* here is invented.';
    const newLine = 'A team keeps a short monthly report. The *content* here is invented.';
    assert.ok(source.split('\n').includes(oldLine), 'fixture paragraph must be one source line');
    const edited = source.replace(oldLine, newLine);
    assert.notEqual(edited, source);

    const put = await fetch(sampleUrl, {
      method: 'PUT',
      headers: { 'content-type': 'text/markdown; charset=utf-8' },
      body: edited,
    });
    assert.equal(put.status, 200);
    assert.deepEqual(await put.json(), { saved: sample, bytes: Buffer.byteLength(edited) });
    assert.equal(readFileSync(join(dir, sample), 'utf8'), edited);

    const before = source.split('\n');
    const after = edited.split('\n');
    assert.equal(after.length, before.length, 'no line was added or removed');
    const changed = before.map((line, index) => (line === after[index] ? -1 : index)).filter((index) => index >= 0);
    assert.deepEqual(changed, [before.indexOf(oldLine)]);
  } finally {
    await run.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('the page and browser modules are served over localhost', async () => {
  const run = await startServer({ dir: demoDir, port: 0 });
  try {
    assert.match(run.url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
    const page = await fetch(run.url);
    assert.equal(page.status, 200);
    const html = await page.text();
    assert.match(html, /type="importmap"/);
    assert.match(html, /Provisional labels: synthetic/);
    for (const path of ['@app/demo/app.js', '@docmodel/src/index.js', '@nm/e/prosemirror-view/dist/index.js']) {
      const res = await fetch(new URL(path, run.url));
      assert.equal(res.status, 200, path);
    }
    assert.equal(run.importMap.imports.docmodel, '/@docmodel/src/index.js');
    assert.ok(run.importMap.imports['@milkdown/core'], 'import map names @milkdown/core');
  } finally {
    await run.close();
  }
});

test('path traversal is refused for reads and writes', async () => {
  const parent = mkdtempSync(join(tmpdir(), 'demo-traversal-'));
  const dir = join(parent, 'samples');
  mkdirSync(dir);
  writeFileSync(join(dir, sample), source);
  writeFileSync(join(parent, 'secret.md'), 'SECRET\n');
  const run = await startServer({ dir, port: 0 });
  try {
    const attempts = ['..%2Fsecret.md', '%2e%2e%2fsecret.md', '%2E%2E/secret.md', '/etc/passwd.md'];
    for (const attempt of attempts) {
      const got = await fetch(new URL(`api/sample/${attempt}`, run.url));
      assert.ok([400, 404].includes(got.status), `GET ${attempt} must be refused, got ${got.status}`);
      const put = await fetch(new URL(`api/sample/${attempt}`, run.url), {
        method: 'PUT',
        headers: { 'content-type': 'text/markdown' },
        body: 'overwritten\n',
      });
      assert.ok([400, 404].includes(put.status), `PUT ${attempt} must be refused, got ${put.status}`);
    }
    assert.equal(readFileSync(join(parent, 'secret.md'), 'utf8'), 'SECRET\n');
    assert.equal(readFileSync(join(dir, sample), 'utf8'), source);
  } finally {
    await run.close();
    rmSync(parent, { recursive: true, force: true });
  }
});

// ED-05: autosave with atomic writes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, readdir, rm, chmod } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { atomicWrite, createAutosave } from '../src/autosave.js';

const modUrl = new URL('../src/autosave.js', import.meta.url).href;
const tmp = () => mkdtemp(join(tmpdir(), 'ed05-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test('atomicWrite replaces content and leaves no temp file', async () => {
  const dir = await tmp();
  const target = join(dir, 'doc.md');
  await writeFile(target, '# Old\n');
  await atomicWrite(target, '# New\n');
  assert.equal(await readFile(target, 'utf8'), '# New\n');
  assert.deepEqual(await readdir(dir), ['doc.md']);
  await rm(dir, { recursive: true });
});

test('failed write leaves original intact and no temp file behind', { skip: process.getuid?.() === 0 }, async () => {
  const dir = await tmp();
  const target = join(dir, 'doc.md');
  await writeFile(target, '# Original\n');
  await chmod(dir, 0o500);
  try {
    await assert.rejects(atomicWrite(target, '# Replacement\n'));
  } finally {
    await chmod(dir, 0o700);
  }
  assert.equal(await readFile(target, 'utf8'), '# Original\n');
  assert.deepEqual(await readdir(dir), ['doc.md']);
  await rm(dir, { recursive: true });
});

test('failed rename removes temp file and rethrows', async () => {
  const dir = await tmp();
  const target = join(dir, 'sub');
  await (await import('node:fs/promises')).mkdir(join(target, 'x'), { recursive: true });
  await assert.rejects(atomicWrite(target, 'text'));
  assert.deepEqual(await readdir(dir), ['sub']);
  await rm(dir, { recursive: true });
});

test('SIGKILL mid-save never leaves a partial target', async () => {
  const dir = await tmp();
  const target = join(dir, 'doc.md');
  const A = '# A\n\n' + 'alpha paragraph text. '.repeat(250000) + '\n';
  const B = '# B\n\n' + 'beta words here. '.repeat(300000) + '\n';
  await writeFile(target, A);
  const script = `import { atomicWrite } from ${JSON.stringify(modUrl)};
const A = '# A\\n\\n' + 'alpha paragraph text. '.repeat(250000) + '\\n';
const B = '# B\\n\\n' + 'beta words here. '.repeat(300000) + '\\n';
const t = ${JSON.stringify(target)}; process.stdout.write('ready\\n');
for (let i = 0; ; i++) await atomicWrite(t, i % 2 ? A : B);`;
  for (const delay of [0, 5, 13, 29, 47, 71, 103, 151]) {
    const child = spawn(process.execPath, ['--input-type=module', '-e', script], { stdio: ['ignore', 'pipe', 'inherit'] });
    await new Promise((r) => child.stdout.once('data', r));
    await sleep(delay);
    const exited = new Promise((r) => child.once('exit', r));
    child.kill('SIGKILL');
    await exited;
    const got = await readFile(target, 'utf8');
    assert.ok(got === A || got === B, `partial target after kill at ${delay}ms (len ${got.length})`);
  }
  const left = (await readdir(dir)).filter((f) => f !== 'doc.md');
  for (const f of left) assert.ok(f.endsWith('.tmp'), `unexpected file ${f}`);
  await rm(dir, { recursive: true });
});

function fakeWriter() {
  const calls = [];
  let inFlight = 0, maxInFlight = 0, failNext = 0;
  const write = async (text) => {
    inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
    await sleep(10);
    inFlight--;
    if (failNext > 0) { failNext--; throw new Error('disk full'); }
    calls.push(text);
  };
  return { write, calls, get max() { return maxInFlight; }, fail(n = 1) { failNext = n; } };
}

test('debounce coalesces several schedule() calls into one write', async () => {
  let md = 'a';
  const w = fakeWriter();
  const s = createAutosave({ getMarkdown: () => md, write: w.write, delayMs: 30 });
  s.schedule(); md = 'ab'; s.schedule(); md = 'abc'; s.schedule();
  await sleep(100);
  assert.deepEqual(w.calls, ['abc']);
  s.dispose();
});

test('unchanged text does not rewrite', async () => {
  const w = fakeWriter();
  const s = createAutosave({ getMarkdown: () => 'same', write: w.write, delayMs: 10 });
  await s.flush();
  await s.flush();
  s.schedule();
  await sleep(50);
  assert.deepEqual(w.calls, ['same']);
  s.dispose();
});

test('failed write keeps text dirty and a later flush retries', async () => {
  const w = fakeWriter();
  const s = createAutosave({ getMarkdown: () => 'doc', write: w.write, delayMs: 10 });
  w.fail();
  await assert.rejects(s.flush(), /disk full/);
  assert.deepEqual(w.calls, []);
  await s.flush();
  assert.deepEqual(w.calls, ['doc']);
  s.dispose();
});

test('writes never overlap', async () => {
  let md = 'v0';
  const w = fakeWriter();
  const s = createAutosave({ getMarkdown: () => md, write: w.write, delayMs: 1 });
  const ps = [];
  for (let i = 1; i <= 5; i++) { md = 'v' + i; ps.push(s.flush()); }
  await Promise.all(ps);
  assert.equal(w.max, 1);
  assert.equal(w.calls.at(-1), 'v5');
  s.dispose();
});

test('dispose cancels a pending scheduled write', async () => {
  const w = fakeWriter();
  const s = createAutosave({ getMarkdown: () => 'x', write: w.write, delayMs: 20 });
  s.schedule();
  s.dispose();
  await sleep(60);
  assert.deepEqual(w.calls, []);
});

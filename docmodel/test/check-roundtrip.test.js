import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkFile } from '../scripts/check-roundtrip.js';

const script = join(dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'check-roundtrip.js');

test('checkFile reports parses, idempotent round-trip and section count', () => {
  const r = checkFile('# A\n\ntext **b** *i*\n\n## B\n\n- x\n- y\n\n| h | k |\n| - | - |\n| 1 | 2 |\n');
  assert.deepEqual(r, { parses: true, roundtrip_idempotent: true, section_count: 2 });
});

test('CLI prints one JSON result per path, errors per file', () => {
  const dir = mkdtempSync(join(tmpdir(), 'rt-'));
  const ok = join(dir, 'ok.md');
  writeFileSync(ok, 'plain\n');
  const missing = join(dir, 'missing.md');
  const out = JSON.parse(execFileSync(process.execPath, [script, ok, missing], { encoding: 'utf8' }));
  assert.equal(out.length, 2);
  assert.deepEqual(out[0], { path: ok, parses: true, roundtrip_idempotent: true, section_count: 0 });
  assert.equal(out[1].path, missing);
  assert.equal(out[1].parses, false);
  assert.ok(out[1].error);
});

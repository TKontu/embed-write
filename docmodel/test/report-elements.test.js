// DM-06: report-specific elements round-trip byte for byte with existing syntax only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { parseMarkdown, serializeMarkdown, openMarkdown } from '../src/index.js';

const dir = fileURLToPath(new URL('./fixtures/report-elements/', import.meta.url));

for (const name of ['numbered-figure', 'numbered-table', 'cross-references', 'units']) {
  test(`report element round-trips byte for byte: ${name}`, () => {
    const src = readFileSync(join(dir, `${name}.md`), 'utf8');
    assert.equal(serializeMarkdown(parseMarkdown(src)), src, 'parse -> serialize equals input bytes');
    const opened = openMarkdown(src);
    assert.equal(opened.readOnly, false, opened.warnings.join('; '));
    assert.deepEqual(opened.warnings, []);
  });
}

test('units fixture keeps the non-breaking space', () => {
  const src = readFileSync(join(dir, 'units.md'), 'utf8');
  assert.ok(src.includes('5 kg'));
  assert.ok(serializeMarkdown(parseMarkdown(src)).includes('5 kg'));
});

test('table cells are not escaped as block line starts', () => {
  const src = '| n | v |\n| --- | --- |\n| 1. | 12.4 |\n| - | # x |\n';
  assert.equal(serializeMarkdown(parseMarkdown(src)), src);
});

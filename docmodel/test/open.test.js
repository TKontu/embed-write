// @ts-check
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { openMarkdown, serializeMarkdown } from '../src/index.js';

const fx = (n) => new URL(`./fixtures/open/${n}`, import.meta.url);
const sha = (b) => createHash('sha256').update(b).digest('hex');

for (const [file, cause] of [['inline-html.md', 'html'], ['strikethrough.md', 'delete']]) {
  test(`known-bad ${file} opens read-only, bytes unchanged`, () => {
    const before = readFileSync(fx(file));
    const res = openMarkdown(before.toString('utf8'));
    const after = readFileSync(fx(file));
    assert.equal(res.readOnly, true);
    assert.equal(res.doc, null);
    assert.equal(res.warnings.length, 1);
    assert.match(res.warnings[0], new RegExp(`"${cause}"`));
    assert.equal(sha(after), sha(before));
    assert.ok(!('markdown' in res) && !('text' in res), 'no rewritten bytes returned');
  });
}

test('clean file opens editable with no warnings', () => {
  const src = readFileSync(fx('clean.md'), 'utf8');
  const res = openMarkdown(src);
  assert.equal(res.readOnly, false);
  assert.deepEqual(res.warnings, []);
  assert.equal(res.doc.type.name, 'doc');
});

test('non-fixed-point serializer opens read-only (injected)', () => {
  let n = 0;
  const unstable = (doc) => serializeMarkdown(doc) + 'x'.repeat(++n) + '\n';
  const res = openMarkdown('# Clean\n\nA plain paragraph.\n', { serialize: unstable });
  assert.equal(res.readOnly, true);
  assert.match(res.warnings[0], /round-trip/);
  assert.ok(res.doc, 'doc still available for read-only display');
});

test('doc JSON drift after re-parse opens read-only (injected)', () => {
  const res = openMarkdown('A plain paragraph.\n', { serialize: () => 'Different.\n' });
  assert.equal(res.readOnly, true);
  assert.match(res.warnings[0], /round-trip/);
});

test('non-Error/other parse failures propagate', () => {
  assert.throws(() => openMarkdown(/** @type {any} */ (42)));
});

test('TOML front matter opens read-only with a warning, bytes unchanged', () => {
  const src = '+++\ntitle = "x"\n+++\n\nBody\n';
  const before = sha(src);
  const res = openMarkdown(src);
  assert.equal(res.readOnly, true);
  assert.equal(res.doc, null);
  assert.equal(res.warnings.length, 1);
  assert.match(res.warnings[0], /TOML front matter/);
  assert.equal(sha(src), before);
});

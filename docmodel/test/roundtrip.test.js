// DM-03: round-trip idempotence over synthetic LLM-built fixtures.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { parseMarkdown, serializeMarkdown, UnsupportedNodeError } from '../src/index.js';

const dir = fileURLToPath(new URL('./fixtures/roundtrip/', import.meta.url));
const json = (doc) => JSON.parse(JSON.stringify(doc.toJSON()));

const REQUIRED = [
  'nested-emphasis', 'reference-links', 'footnotes', 'aligned-table', 'code-fence-markdown',
  'html-blocks', 'hard-breaks', 'front-matter', 'setext-headings', 'table-pipe-in-code',
];
const fixtures = readdirSync(dir).filter((f) => f.endsWith('.md')).sort();

test('fixture corpus covers the required constructs', () => {
  for (const name of REQUIRED) assert.ok(fixtures.includes(`${name}.md`), name);
});

for (const file of fixtures) {
  test(`round-trip: ${file}`, () => {
    const src = readFileSync(join(dir, file), 'utf8');
    const doc1 = parseMarkdown(src);
    const out1 = serializeMarkdown(doc1);
    const doc2 = parseMarkdown(out1);
    assert.deepEqual(json(doc2), json(doc1), 'parse -> serialize -> parse doc JSON equal');
    const out2 = serializeMarkdown(doc2);
    assert.equal(out2, out1, 'serialize is a fixed point after one pass');
  });
}

test('table cell code span with | keeps one cell and its content', () => {
  const doc = parseMarkdown(readFileSync(join(dir, 'table-pipe-in-code.md'), 'utf8'));
  const row = doc.firstChild.child(1);
  assert.equal(row.childCount, 2);
  assert.equal(row.firstChild.textContent, 'a | b');
});

// Rejected by the current UnsupportedNodeError policy: asserted to throw, not skipped.
const REJECTED = {
  'inline HTML': 'Text with <span>inline</span> html.\n',
  strikethrough: 'Some ~~struck~~ text.\n',
};
for (const [name, src] of Object.entries(REJECTED)) {
  test(`rejected: ${name} throws UnsupportedNodeError`, () => {
    assert.throws(() => parseMarkdown(src), UnsupportedNodeError);
  });
}

// TOML front matter is NOT rejected at this base: remark-frontmatter is configured for yaml only,
// so a +++ block parses as paragraph text (residual: contradicts the DM-01 record; policy is DM-05).
test('TOML front matter: parsed as paragraph text, not front_matter, and round-trips', () => {
  const src = '+++\ntitle = "x"\n+++\n\nbody\n';
  const doc1 = parseMarkdown(src);
  assert.equal(doc1.firstChild.type.name, 'paragraph');
  const out1 = serializeMarkdown(doc1);
  assert.deepEqual(json(parseMarkdown(out1)), json(doc1));
  assert.equal(serializeMarkdown(parseMarkdown(out1)), out1);
});

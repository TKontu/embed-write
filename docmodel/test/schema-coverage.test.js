// ED-01 / DM-03: every schema node and mark type appears in at least one round-trip fixture.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { parseMarkdown, schema } from '../src/index.js';

const dir = fileURLToPath(new URL('./fixtures/roundtrip/', import.meta.url));

test('every schema node and mark type occurs in a DM-03 round-trip fixture', () => {
  const nodes = new Set();
  const marks = new Set();
  for (const f of readdirSync(dir).filter((x) => x.endsWith('.md'))) {
    const doc = parseMarkdown(readFileSync(join(dir, f), 'utf8'));
    nodes.add(doc.type.name);
    doc.descendants((n) => {
      nodes.add(n.type.name);
      for (const m of n.marks) marks.add(m.type.name);
    });
  }
  const missing = [];
  schema.spec.nodes.forEach((name) => { if (!nodes.has(name)) missing.push(`node:${name}`); });
  schema.spec.marks.forEach((name) => { if (!marks.has(name)) missing.push(`mark:${name}`); });
  assert.deepEqual(missing, [], `schema types absent from all round-trip fixtures: ${missing.join(', ')}`);
});

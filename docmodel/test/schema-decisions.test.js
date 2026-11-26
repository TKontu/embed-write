// ED-02: docs/schema-decisions.md node/mark table lists exactly the schema's node and mark names.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { schema } from '../src/index.js';

const doc = readFileSync(new URL('../../docs/schema-decisions.md', import.meta.url), 'utf8');

/** @param {string} md */
export function tableNames(md) {
  const m = /<!-- schema-table:start -->([\s\S]*?)<!-- schema-table:end -->/.exec(md);
  assert.ok(m, 'schema-table markers missing');
  const nodes = [];
  const marks = [];
  for (const line of m[1].split('\n')) {
    const cells = line.split('|').map((c) => c.trim());
    if (cells[1] === 'node') nodes.push(cells[2]);
    else if (cells[1] === 'mark') marks.push(cells[2]);
  }
  return { nodes, marks };
}

const names = (spec) => { const out = []; spec.forEach((n) => out.push(n)); return out; };

test('schema-decisions.md table lists exactly the schema nodes and marks', () => {
  const { nodes, marks } = tableNames(doc);
  assert.deepEqual([...nodes].sort(), names(schema.spec.nodes).sort());
  assert.deepEqual([...marks].sort(), names(schema.spec.marks).sort());
  assert.equal(new Set(nodes).size, nodes.length, 'duplicate node row');
  assert.equal(new Set(marks).size, marks.length, 'duplicate mark row');
});

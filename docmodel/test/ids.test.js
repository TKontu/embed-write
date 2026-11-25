// NI-01: ULID generation and block node id assignment.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { parseMarkdown, serializeMarkdown, schema, ulid, assignIds } from '../src/index.js';

const CROCKFORD = /^[0-9ABCDEFGHJKMNPQRSTVWXYZ]{26}$/;
const ALPHA = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
const decodeTime = (id) => [...id.slice(0, 10)].reduce((t, c) => t * 32 + ALPHA.indexOf(c), 0);
const json = (doc) => JSON.parse(JSON.stringify(doc.toJSON()));
const dir = fileURLToPath(new URL('./fixtures/roundtrip/', import.meta.url));
const fixtures = readdirSync(dir).filter((f) => f.endsWith('.md')).sort();

/** @param {import('prosemirror-model').Node} doc */
const blockIds = (doc) => {
  const out = [];
  doc.descendants((n) => {
    if (n.type.spec.attrs && 'id' in n.type.spec.attrs) out.push({ type: n.type.name, id: n.attrs.id });
  });
  return out;
};

const NESTED = '# T\n\n> quote\n>\n> - a\n>   - b\n\n1. one\n2. two\n   - [ ] task\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n';

test('ulid: 26 Crockford chars, time prefix decodes to injected time', () => {
  const t = 1_700_000_000_123;
  const id = ulid(t);
  assert.match(id, CROCKFORD);
  assert.equal(decodeTime(id), t);
  assert.equal(decodeTime(ulid(0)), 0);
  assert.equal(decodeTime(ulid(2 ** 48 - 1)), 2 ** 48 - 1);
  assert.throws(() => ulid(-1), RangeError);
});

test('ulid: injected random source is used', () => {
  const zero = (buf) => buf.fill(0);
  assert.equal(ulid(5, zero), '000000000500000000000000000'.slice(0, 26));
  assert.equal(ulid(7, (b) => b.fill(31)).slice(10), 'Z'.repeat(16));
});

test('ulid: 1000 ids in one millisecond are strictly increasing', () => {
  const t = 1_800_000_000_000;
  const ids = Array.from({ length: 1000 }, () => ulid(t));
  for (let i = 1; i < ids.length; i++) assert.ok(ids[i - 1] < ids[i], `${ids[i - 1]} < ${ids[i]}`);
  assert.equal(new Set(ids).size, 1000);
  for (const id of ids) assert.equal(decodeTime(id), t);
});

test('schema: every block node type has id defaulting to null; inline nodes do not', () => {
  for (const [name, type] of Object.entries(schema.nodes)) {
    const isBlock = type.isBlock && name !== 'doc';
    assert.equal(!!type.spec.attrs && 'id' in type.spec.attrs, isBlock, name);
    if (isBlock) assert.equal(type.create().attrs.id ?? null, null, name);
  }
});

test('parseMarkdown leaves ids null', () => {
  for (const b of blockIds(parseMarkdown(NESTED))) assert.equal(b.id, null, b.type);
});

test('assignIds: unique id on every block node incl. nested list items and quote children', () => {
  const doc = parseMarkdown(NESTED);
  const ids = blockIds(assignIds(doc));
  const types = new Set(ids.map((b) => b.type));
  for (const t of ['heading', 'blockquote', 'paragraph', 'bullet_list', 'ordered_list', 'list_item',
    'table', 'table_row', 'table_cell', 'thematic_break']) assert.ok(types.has(t), t);
  for (const b of ids) assert.match(b.id, CROCKFORD, b.type);
  assert.equal(new Set(ids.map((b) => b.id)).size, ids.length);
  assert.equal(ids.length, blockIds(doc).length);
});

test('assignIds: input not mutated; new doc returned', () => {
  const doc = parseMarkdown(NESTED);
  const before = json(doc);
  const out = assignIds(doc);
  assert.notEqual(out, doc);
  assert.deepEqual(json(doc), before);
});

test('assignIds: existing ids preserved, duplicates first-wins, idempotent', () => {
  const p = (id, text) => schema.nodes.paragraph.create({ id }, schema.text(text));
  const doc = schema.nodes.doc.create(null, [p('KEEP', 'a'), p(null, 'b'), p('KEEP', 'c'), p('OTHER', 'd')]);
  const out = assignIds(doc);
  const ids = blockIds(out).map((b) => b.id);
  assert.equal(ids[0], 'KEEP');
  assert.equal(ids[3], 'OTHER');
  assert.match(ids[1], CROCKFORD);
  assert.match(ids[2], CROCKFORD);
  assert.notEqual(ids[1], ids[2]);
  assert.deepEqual(json(assignIds(out)), json(out));
  assert.equal(out.child(2).textContent, 'c');
});

test('assignIds: injectable clock', () => {
  const ids = blockIds(assignIds(parseMarkdown('a\n\nb\n'), { now: () => 42 }));
  for (const b of ids) assert.equal(decodeTime(b.id), 42);
});

for (const file of fixtures) {
  test(`serialize ignores ids: ${file}`, () => {
    const doc = parseMarkdown(readFileSync(join(dir, file), 'utf8'));
    const withIds = assignIds(doc);
    assert.ok(blockIds(withIds).every((b) => b.id));
    assert.equal(serializeMarkdown(withIds), serializeMarkdown(doc));
  });
}

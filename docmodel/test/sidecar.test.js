import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as model from '../src/index.js';

const fixture = '# Title\n\n> Quote\n>\n> - first\n>   - nested\n\n| a | b |\n| - | - |\n| c | d |\n\n---\n';
const docWithIds = () => model.assignIds(model.parseMarkdown(fixture));

test('build records every id-bearing node in document order with resolving paths and hashes', () => {
  assert.equal(typeof model.buildSidecar, 'function');
  const doc = docWithIds();
  const before = doc.toJSON();
  const expected = [];
  doc.descendants(node => {
    if (Object.hasOwn(node.attrs, 'id')) expected.push(node);
  });
  const sidecar = model.buildSidecar(doc);
  assert.equal(sidecar.version, 1);
  assert.deepEqual(sidecar.nodes.map(n => n.id), expected.map(n => n.attrs.id));
  sidecar.nodes.forEach((entry, i) => {
    const node = entry.path.reduce((parent, index) => parent.child(index), doc);
    assert.equal(node, expected[i]);
    assert.equal(entry.hash, model.nodeHash(node));
    assert.equal(entry.type, node.type.name);
  });
  assert.deepEqual(doc.toJSON(), before);
});

test('build rejects unassigned ids with guidance to assign them first', () => {
  assert.throws(() => model.buildSidecar(model.parseMarkdown(fixture)), /assignIds/);
});

test('serialization is canonical, repeatable and byte-stable after parsing', () => {
  assert.equal(typeof model.serializeSidecar, 'function');
  assert.equal(typeof model.parseSidecar, 'function');
  const doc = docWithIds();
  const sidecar = model.buildSidecar(doc);
  const text = model.serializeSidecar(sidecar);
  assert.equal(text, JSON.stringify(sidecar, null, 2) + '\n');
  assert.equal(text, model.serializeSidecar(model.buildSidecar(doc)));
  assert.equal(text, model.serializeSidecar(model.parseSidecar(text)));
  const reordered = { nodes: sidecar.nodes.map(({type, hash, path, id}) => ({type, hash, path, id})), version: 1 };
  assert.equal(model.serializeSidecar(reordered), text);
});

test('optional reserved genre and links survive without being added when absent', () => {
  assert.equal(typeof model.parseSidecar, 'function');
  const bare = { version: 1, nodes: [] };
  const reserved = { ...bare, genre: null, links: [] };
  for (const value of [bare, reserved]) {
    assert.deepEqual(model.parseSidecar(model.serializeSidecar(value)), value);
  }
});

test('malformed JSON, unknown versions and duplicate ids have clear errors', () => {
  assert.equal(typeof model.parseSidecar, 'function');
  assert.throws(() => model.parseSidecar('{'), /sidecar.*JSON/i);
  assert.throws(() => model.parseSidecar('{"version":2,"nodes":[]}'), /version/i);
  const sidecar = model.buildSidecar(docWithIds());
  sidecar.nodes.push(sidecar.nodes[0]);
  assert.throws(() => model.parseSidecar(JSON.stringify(sidecar)), /duplicate.*id/i);
});

test('invalid record shapes are rejected at the JSON boundary', () => {
  assert.equal(typeof model.parseSidecar, 'function');
  const node = { id: 'existing-id', path: [0], hash: 'a'.repeat(64), type: 'paragraph' };
  const badNodes = [null, [], {}, ...[
    { id: null }, { id: '' }, { id: 7 }, { path: '0' }, { path: [-1] },
    { path: [0.5] }, { path: [Number.MAX_SAFE_INTEGER + 1] },
    { hash: 'bad' }, { type: '' }, { type: null },
  ].map(patch => ({ ...node, ...patch }))];
  for (const value of [null, [], {}, {version: 1}, {version: 1, nodes: {}},
    ...badNodes.map(n => ({version: 1, nodes: [n]})),
    {version: 1, nodes: [], genre: 7}, {version: 1, nodes: [], links: {}}]) {
    assert.throws(() => model.parseSidecar(JSON.stringify(value)), /sidecar/i);
  }
});

test('sidecar path appends the suffix to the complete document path', () => {
  assert.equal(typeof model.sidecarPath, 'function');
  assert.equal(model.sidecarPath('a/b.md'), 'a/b.md.stw.json');
});

// SL-01: genre binding (LLM-built shared fixture; Python twin in tests/test_genre.py).
const binding = JSON.parse(readFileSync(new URL('./fixtures/genre-binding.json', import.meta.url), 'utf8'));

test('a valid genre binding round-trips canonically', () => {
  const reordered = { genre_hash: binding.genre_hash, genre_version: binding.genre_version, genre: binding.genre };
  const text = model.serializeSidecar({ version: 1, nodes: [], genre: reordered });
  assert.deepEqual(Object.keys(JSON.parse(text).genre), ['genre', 'genre_version', 'genre_hash']);
  const parsed = model.parseSidecar(text);
  assert.deepEqual(parsed.genre, binding);
  assert.equal(model.serializeSidecar(parsed), text);
  assert.deepEqual(model.parseSidecar(model.serializeSidecar(parsed)), parsed);
});

test('each invalid genre binding names the bad key', () => {
  const cases = [
    [7, /^Error: sidecar: genre/], ['x', /^Error: sidecar: genre/], [[], /^Error: sidecar: genre/],
    [{ genre_version: 1, genre_hash: binding.genre_hash }, /^Error: sidecar: genre.*\bgenre\b/],
    [{ genre: 'g', genre_hash: binding.genre_hash }, /^Error: sidecar: genre.*genre_version/],
    [{ genre: 'g', genre_version: 1 }, /^Error: sidecar: genre.*genre_hash/],
    [{ ...binding, extra: 1 }, /^Error: sidecar: genre.*extra/],
    [{ ...binding, genre: '' }, /^Error: sidecar: genre.*\bgenre\b/],
    [{ ...binding, genre: 3 }, /^Error: sidecar: genre.*\bgenre\b/],
    ...[0, 1.5, true, '1', -1].map(v => [{ ...binding, genre_version: v }, /^Error: sidecar: genre.*genre_version/]),
    ...[binding.genre_hash.toUpperCase(), 'ab', 'z'.repeat(64), 7].map(v =>
      [{ ...binding, genre_hash: v }, /^Error: sidecar: genre.*genre_hash/]),
  ];
  for (const [genre, pattern] of cases) {
    assert.throws(() => model.parseSidecar(JSON.stringify({ version: 1, nodes: [], genre })), pattern,
      JSON.stringify(genre));
  }
});

test('bindGenre returns a new validated sidecar without mutating its input', () => {
  const sidecar = { version: 1, nodes: [], links: [] };
  const before = structuredClone(sidecar);
  const bound = model.bindGenre(sidecar, binding);
  assert.deepEqual(sidecar, before);
  assert.deepEqual(bound, { version: 1, nodes: [], genre: binding, links: [] });
  assert.notEqual(bound.genre, binding);
  assert.deepEqual(model.bindGenre(bound, null).genre, null);
  assert.deepEqual(bound.genre, binding);
  assert.throws(() => model.bindGenre(sidecar, { ...binding, genre_version: 0 }), /sidecar: genre.*genre_version/);
});

test('genreBindingStatus distinguishes unbound, match, stale and other', () => {
  const bound = model.bindGenre({ version: 1, nodes: [] }, binding);
  assert.equal(model.genreBindingStatus({ version: 1, nodes: [] }, binding), 'unbound');
  assert.equal(model.genreBindingStatus({ version: 1, nodes: [], genre: null }, binding), 'unbound');
  assert.equal(model.genreBindingStatus(bound, { ...binding }), 'match');
  assert.equal(model.genreBindingStatus(bound, { ...binding, genre_version: 2 }), 'stale');
  assert.equal(model.genreBindingStatus(bound, { ...binding, genre_hash: 'b'.repeat(64) }), 'stale');
  assert.equal(model.genreBindingStatus(bound, { ...binding, genre: 'another-genre' }), 'other');
});

test('SL-02: valid links round-trip canonically with sorted sources', () => {
  const value = { version: 1, nodes: [], links: [
    { sources: ['b', 'a'], to: 9, from: 2, node: 'n1' },
    { node: 'n2', from: 0, to: 1, sources: ['x'] },
  ] };
  const text = model.serializeSidecar(value);
  const parsed = model.parseSidecar(text);
  assert.deepEqual(parsed.links, [
    { node: 'n1', from: 2, to: 9, sources: ['a', 'b'] },
    { node: 'n2', from: 0, to: 1, sources: ['x'] },
  ]);
  assert.deepEqual(Object.keys(parsed.links[0]), ['node', 'from', 'to', 'sources']);
  assert.equal(model.serializeSidecar(parsed), text);
});

test('SL-02: invalid link shapes are rejected with sidecar: links errors', () => {
  const ok = { node: 'n', from: 0, to: 2, sources: ['s'] };
  const bad = [null, [], 'x', { ...ok, extra: 1 }, { ...ok, node: '' }, { ...ok, node: 3 },
    { ...ok, from: -1 }, { ...ok, from: 0.5 }, { ...ok, to: 0 }, { ...ok, from: 2, to: 2 },
    { ...ok, to: '2' }, { ...ok, sources: [] }, { ...ok, sources: 's' }, { ...ok, sources: [''] },
    { ...ok, sources: ['s', 's'] }, { ...ok, sources: [1] }, { node: 'n', from: 0, to: 2 }];
  for (const entry of bad) {
    assert.throws(() => model.parseSidecar(JSON.stringify({ version: 1, nodes: [], links: [ok, entry] })),
      /^Error: sidecar: links\[1\]/, JSON.stringify(entry));
  }
});

test('SL-03: valid provenance round-trips canonically, sorted, human entries omitted', () => {
  const value = { version: 1, nodes: [], provenance: [
    { run: 'run-2', kind: 'machine-edited', node: 'n2' },
    { node: 'h1', kind: 'human', run: null },
    { node: 'n1', kind: 'machine', run: 'run-1' },
  ] };
  const text = model.serializeSidecar(value);
  const parsed = model.parseSidecar(text);
  assert.deepEqual(parsed.provenance, [
    { node: 'n1', kind: 'machine', run: 'run-1' },
    { node: 'n2', kind: 'machine-edited', run: 'run-2' },
  ]);
  assert.deepEqual(Object.keys(parsed.provenance[1]), ['node', 'kind', 'run']);
  assert.equal(model.serializeSidecar(parsed), text);
  const empty = { version: 1, nodes: [], provenance: [] };
  assert.deepEqual(model.parseSidecar(model.serializeSidecar(empty)), empty);
});

test('SL-03: invalid provenance shapes are rejected with sidecar: provenance errors', () => {
  const ok = { node: 'n1', kind: 'machine', run: 'r' };
  assert.throws(() => model.parseSidecar(JSON.stringify({ version: 1, nodes: [], provenance: {} })),
    /^Error: sidecar: provenance must be an array/);
  for (const entry of [null, [], 'x', { ...ok, extra: 1 }, { ...ok, node: '' }, { ...ok, node: 7 },
    { kind: 'machine', run: 'r' }, { ...ok, kind: 'robot' }, { ...ok, run: null }, { ...ok, run: '' },
    { node: 'n2', kind: 'machine' }, { node: 'n2', kind: 'human', run: 'r' }, { ...ok }]) {
    assert.throws(() => model.parseSidecar(JSON.stringify({ version: 1, nodes: [], provenance: [ok, entry] })),
      /^Error: sidecar: provenance\[1\]/, JSON.stringify(entry));
  }
});

test('SL-03: sidecars without provenance serialize byte-identically to before', () => {
  const doc = docWithIds();
  const bare = model.buildSidecar(doc);
  const text = model.serializeSidecar(bare);
  assert.equal(text, JSON.stringify(bare, null, 2) + '\n');
  assert.ok(!text.includes('provenance'));
  const withLinks = { ...bare, genre: null, links: [] };
  assert.equal(model.serializeSidecar(withLinks), JSON.stringify(withLinks, null, 2) + '\n');
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
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

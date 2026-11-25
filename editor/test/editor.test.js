// ED-01: createEditor over docmodel's schema, exercised headless under jsdom.
import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { schema, parseMarkdown, serializeMarkdown, overlayKey } = await import('docmodel');

const dir = fileURLToPath(new URL('../../docmodel/test/fixtures/roundtrip/', import.meta.url));
const fixtures = readdirSync(dir).filter((f) => f.endsWith('.md')).sort();
const mount = () => document.body.appendChild(document.createElement('div'));

test('fixtures are present', () => assert.ok(fixtures.length >= 10, String(fixtures.length)));

for (const file of fixtures) {
  test(`getMarkdown equals docmodel round-trip: ${file}`, async () => {
    const src = readFileSync(join(dir, file), 'utf8');
    const ed = await createEditor({ root: mount(), markdown: src });
    try {
      assert.equal(ed.getMarkdown(), serializeMarkdown(parseMarkdown(src)));
    } finally { await ed.destroy(); }
  });
}

test('editor state schema is docmodel schema (names and attrs)', async () => {
  const ed = await createEditor({ root: mount(), markdown: '# a\n' });
  try {
    const s = ed.view.state.schema;
    assert.equal(s, schema);
    assert.deepEqual(new Set(Object.keys(s.nodes)), new Set(Object.keys(schema.nodes)));
    assert.deepEqual(new Set(Object.keys(s.marks)), new Set(Object.keys(schema.marks)));
    for (const n of Object.keys(schema.nodes)) assert.deepEqual(Object.keys(s.nodes[n].attrs), Object.keys(schema.nodes[n].attrs), n);
  } finally { await ed.destroy(); }
});

test('overlayPlugin and idPlugin are in editor state plugins', async () => {
  const ed = await createEditor({ root: mount(), markdown: 'para one\n\npara two\n' });
  try {
    const { state } = ed.view;
    assert.ok(state.plugins.some((p) => p.spec.key === overlayKey), 'overlayPlugin');
    assert.ok(state.plugins.some((p) => p.spec.appendTransaction && !p.spec.key), 'idPlugin candidate');
    // Behavioural proof: an edit triggers idPlugin to assign ids to block nodes.
    ed.view.dispatch(state.tr.insertText('X', 1));
    const ids = [];
    ed.view.state.doc.forEach((n) => ids.push(n.attrs.id));
    assert.ok(ids.every((id) => typeof id === 'string' && id.length === 26), JSON.stringify(ids));
    // Overlay meta flows through the editor's plugin.
    ed.view.dispatch(ed.view.state.tr.setMeta(overlayKey, { add: [{ from: 1, to: 3 }] }));
    assert.equal(overlayKey.getState(ed.view.state).find().length, 1);
    assert.equal(ed.getMarkdown(), 'Xpara one\n\npara two\n');
  } finally { await ed.destroy(); }
});

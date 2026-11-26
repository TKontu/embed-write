// ED-03: one Markdown serializer. Every editor path that produces Markdown goes through
// docmodel's serializeMarkdown; no second serializer is imported or declared.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, extname } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { serializeMarkdown } = await import('docmodel');

const fixDir = fileURLToPath(new URL('../../docmodel/test/fixtures/roundtrip/', import.meta.url));
const fixtures = readdirSync(fixDir).filter((f) => f.endsWith('.md')).sort();
const mount = () => document.body.appendChild(document.createElement('div'));

test('round-trip fixtures are present', () => assert.ok(fixtures.length >= 10, String(fixtures.length)));

for (const file of fixtures) {
  test(`getMarkdown and source view equal serializeMarkdown(view.state.doc): ${file}`, async () => {
    const src = readFileSync(join(fixDir, file), 'utf8');
    const ed = await createEditor({ root: mount(), markdown: src });
    try {
      const expected = serializeMarkdown(ed.view.state.doc);
      assert.equal(ed.getMarkdown(), expected);
      ed.showSource();
      const ta = /** @type {HTMLTextAreaElement} */ (ed.view.dom.ownerDocument.querySelector('textarea'));
      assert.ok(ta, 'source view textarea');
      assert.equal(ta.value, expected);
      assert.equal(ed.getMarkdown(), expected);
    } finally { await ed.destroy(); }
  });
}

// Packages that serialize Markdown (or HTML->Markdown). Only docmodel may do this.
export const FORBIDDEN_PACKAGES = [
  'remark-stringify', 'mdast-util-to-markdown', 'prosemirror-markdown', '@milkdown/preset-commonmark',
  '@milkdown/preset-gfm', '@milkdown/plugin-markdown', 'turndown', 'marked', 'markdown-it', 'remark',
  'unified', 'micromark', 'showdown', 'tiptap-markdown', '@tiptap/pm/markdown',
];
// Milkdown's own serializer surface (from @milkdown/transformer or re-exported via @milkdown/core).
const FORBIDDEN_IDENTIFIERS = ['serializerCtx', 'Serializer', 'SerializerReady', 'SerializerState', 'getMarkdown as'];

/** @param {string} text @returns {string[]} violations */
export function scanSource(text) {
  const out = [];
  const specRe = /(?:import\s[^'"]*?from\s*|import\s*\(\s*|import\s+|require\s*\(\s*|export\s[^'"]*?from\s*)['"]([^'"]+)['"]/g;
  for (const m of text.matchAll(specRe)) {
    const spec = m[1];
    if (FORBIDDEN_PACKAGES.some((p) => spec === p || spec.startsWith(`${p}/`))) out.push(`imports ${spec}`);
    if (spec.startsWith('@milkdown/transformer')) out.push(`imports ${spec}`);
  }
  for (const id of FORBIDDEN_IDENTIFIERS.slice(0, 4)) {
    if (new RegExp(`\\b${id}\\b`).test(text)) out.push(`uses ${id}`);
  }
  return out;
}

const roots = ['../src/', '../demo/'].map((p) => fileURLToPath(new URL(p, import.meta.url)));
/** @param {string} d @returns {string[]} */
const walk = (d) => readdirSync(d).flatMap((f) => {
  const p = join(d, f);
  return statSync(p).isDirectory() ? walk(p) : ['.js', '.mjs', '.cjs', '.ts', '.html'].includes(extname(p)) ? [p] : [];
});

test('scanner catches a forbidden import (self-check)', () => {
  assert.deepEqual(scanSource("import { x } from 'remark-stringify';"), ['imports remark-stringify']);
  assert.deepEqual(scanSource("import { serializerCtx } from '@milkdown/core';"), ['uses serializerCtx']);
  assert.ok(scanSource("import { Serializer } from '@milkdown/transformer';").length > 0);
  assert.deepEqual(scanSource("import { serializeMarkdown } from 'docmodel';"), []);
});

test('editor/src and editor/demo import no Markdown serializer other than docmodel', () => {
  const files = roots.flatMap(walk);
  assert.ok(files.length >= 10, String(files.length));
  const bad = files.flatMap((f) => scanSource(readFileSync(f, 'utf8')).map((v) => `${f}: ${v}`));
  assert.deepEqual(bad, []);
});

test('editor/package.json declares no Markdown serializer package', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  const declared = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies, ...pkg.optionalDependencies, ...pkg.peerDependencies });
  assert.deepEqual(declared.filter((d) => FORBIDDEN_PACKAGES.includes(d)), []);
});

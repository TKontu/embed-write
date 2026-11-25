import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseMarkdown, normalizeHeading, mapSectionTypes } from '../src/index.js';

// LLM-built synthetic section types (mirrors tests/fixtures/genre_synthetic_sections.json).
const TYPES = [
  { id: 'findings', name: 'Findings', headings: ['Findings', 'Key findings'] },
  { id: 'conclusions', name: 'Conclusions', headings: ['Conclusions', 'Conclusions and recommendations'] },
];

test('fixture parity: normalizeHeading matches heading-normalize.json', () => {
  const cases = JSON.parse(readFileSync(new URL('./fixtures/heading-normalize.json', import.meta.url), 'utf8'));
  assert.ok(cases.length > 10);
  for (const c of cases) assert.equal(normalizeHeading(c.input), c.expected, JSON.stringify(c.input));
});

test('maps numbered, colon and case variants; reports unknown as unmapped', () => {
  const md = '# 1. Introduction\n\np\n\n## 2. KEY FINDINGS:\n\nq\n\n#### IV. Conclusions and Recommendations.\n\n## Annex';
  const doc = parseMarkdown(md);
  const before = JSON.stringify(doc.toJSON());
  const r = mapSectionTypes(doc, TYPES);
  assert.deepEqual(r.mapped, [
    { heading: '2. KEY FINDINGS:', index: 2, level: 2, sectionType: 'findings' },
    { heading: 'IV. Conclusions and Recommendations.', index: 4, level: 4, sectionType: 'conclusions' },
  ]);
  assert.deepEqual(r.unmapped, [
    { heading: '1. Introduction', index: 0, level: 1 },
    { heading: 'Annex', index: 5, level: 2 },
  ]);
  assert.equal(JSON.stringify(doc.toJSON()), before);
});

test('document order across nesting and siblings', () => {
  const r = mapSectionTypes(parseMarkdown('# Findings\n\n## Other\n\n# Conclusions'), TYPES);
  assert.deepEqual(r.mapped.map((m) => m.index), [0, 2]);
  assert.deepEqual(r.unmapped.map((m) => m.index), [1]);
});

test('doc without headings: both empty', () => {
  assert.deepEqual(mapSectionTypes(parseMarkdown('just text\n\nmore'), TYPES), { mapped: [], unmapped: [] });
});

test('no fuzzy matching', () => {
  const r = mapSectionTypes(parseMarkdown('# Finding\n\n# Findingss'), TYPES);
  assert.equal(r.mapped.length, 0);
  assert.equal(r.unmapped.length, 2);
});

test('empty or missing section types: everything unmapped', () => {
  const doc = parseMarkdown('# Findings');
  assert.equal(mapSectionTypes(doc, []).unmapped.length, 1);
  assert.equal(mapSectionTypes(doc, undefined).unmapped.length, 1);
});

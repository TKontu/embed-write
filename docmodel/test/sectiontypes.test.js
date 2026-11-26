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

// BH-06: section skeleton for a new report.
import { sectionSkeleton, serializeMarkdown } from '../src/index.js';

const SKEL_TYPES = [
  { id: 'intro', name: 'Introduction', headings: ['Introduction', 'Background'] },
  { id: 'findings', name: 'Key results', headings: ['Findings', 'Key findings'] },
  { id: 'conclusions', name: 'Conclusions:', headings: ['Conclusions', 'Summary'] },
];

test('sectionSkeleton: genre order, name vs alias fallback, round-trips byte for byte', () => {
  const md = sectionSkeleton(SKEL_TYPES);
  assert.equal(md, '## Introduction\n\n## Findings\n\n## Conclusions:\n');
  assert.equal(serializeMarkdown(parseMarkdown(md)), md);
  const r = mapSectionTypes(parseMarkdown(md), SKEL_TYPES);
  assert.deepEqual(r.mapped.map((m) => m.sectionType), ['intro', 'findings', 'conclusions']);
  assert.deepEqual(r.unmapped, []);
});

test('sectionSkeleton: title is the only unmapped heading; level option', () => {
  const md = sectionSkeleton(SKEL_TYPES, { title: 'Annual report', level: 3 });
  assert.equal(md, '# Annual report\n\n### Introduction\n\n### Findings\n\n### Conclusions:\n');
  assert.equal(serializeMarkdown(parseMarkdown(md)), md);
  const r = mapSectionTypes(parseMarkdown(md), SKEL_TYPES);
  assert.deepEqual(r.mapped.map((m) => [m.sectionType, m.level]), [['intro', 3], ['findings', 3], ['conclusions', 3]]);
  assert.deepEqual(r.unmapped, [{ heading: 'Annual report', index: 0, level: 1 }]);
  assert.equal(sectionSkeleton(SKEL_TYPES, { level: 1 }).split('\n')[0], '# Introduction');
  for (const level of [0, 7, 2.5, '2', null]) {
    assert.throws(() => sectionSkeleton(SKEL_TYPES, { level }), TypeError, String(level));
  }
});

test('sectionSkeleton: absent or empty types', () => {
  assert.equal(sectionSkeleton(undefined), '');
  assert.equal(sectionSkeleton([]), '');
  assert.equal(sectionSkeleton([], { title: 'T' }), '# T\n');
  assert.equal(sectionSkeleton(undefined, { title: 'T' }), '# T\n');
});

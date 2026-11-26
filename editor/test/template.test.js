// BH-06: insertSectionTemplate starts an empty report from the genre's section skeleton.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, insertSectionTemplate, undo } = await import('../src/index.js');
const { sectionSkeleton } = await import('docmodel');

const mount = () => document.body.appendChild(document.createElement('div'));
// Synthetic section types only.
const TYPES = [
  { name: 'Alpha', headings: ['Alpha', 'First Part'] },
  { name: 'beta-part', headings: ['Beta Section'] },
  { name: 'Gamma', headings: ['Gamma'] },
];

test('empty editor: skeleton inserted byte for byte, returns true', async () => {
  const ed = await createEditor({ root: mount(), markdown: '' });
  try {
    assert.equal(insertSectionTemplate(ed, TYPES), true);
    assert.equal(ed.getMarkdown(), sectionSkeleton(TYPES));
  } finally { await ed.destroy(); }
});

test('whitespace-only editor counts as empty', async () => {
  const ed = await createEditor({ root: mount(), markdown: '  \n\n ' });
  try {
    assert.equal(insertSectionTemplate(ed, TYPES), true);
    assert.equal(ed.getMarkdown(), sectionSkeleton(TYPES));
  } finally { await ed.destroy(); }
});

test('one undo restores the empty document', async () => {
  const ed = await createEditor({ root: mount(), markdown: '' });
  try {
    const before = ed.getMarkdown();
    insertSectionTemplate(ed, TYPES);
    assert.equal(undo(ed), true);
    assert.equal(ed.getMarkdown(), before);
    assert.equal(ed.getMarkdown().trim(), '');
  } finally { await ed.destroy(); }
});

test('non-empty editor: returns false and changes nothing', async () => {
  const src = '# Draft\n\nSome text.\n';
  const ed = await createEditor({ root: mount(), markdown: src });
  try {
    const before = ed.getMarkdown();
    assert.equal(insertSectionTemplate(ed, TYPES), false);
    assert.equal(ed.getMarkdown(), before);
    assert.equal(undo(ed), false);
  } finally { await ed.destroy(); }
});

test('title and level pass through', async () => {
  const ed = await createEditor({ root: mount(), markdown: '' });
  try {
    const opts = { title: 'Report X', level: 3 };
    assert.equal(insertSectionTemplate(ed, TYPES, opts), true);
    assert.equal(ed.getMarkdown(), sectionSkeleton(TYPES, opts));
    assert.match(ed.getMarkdown(), /^# Report X\n\n### Alpha\n/);
  } finally { await ed.destroy(); }
});

test('invalid level throws TypeError and leaves the doc unchanged', async () => {
  const ed = await createEditor({ root: mount(), markdown: '' });
  try {
    const before = ed.getMarkdown();
    assert.throws(() => insertSectionTemplate(ed, TYPES, { level: 7 }), TypeError);
    assert.throws(() => insertSectionTemplate(ed, TYPES, { level: 1.5 }), TypeError);
    assert.equal(ed.getMarkdown(), before);
    assert.equal(undo(ed), false);
  } finally { await ed.destroy(); }
});

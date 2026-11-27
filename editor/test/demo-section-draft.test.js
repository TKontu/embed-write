// CO-14 (c, D-015): the demo's section-correction draft (keep / remove / add boundary) and the Save
// payload, as pure logic (demo/section-draft.js, imported by demo/app.js). Synthetic data only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createSectionDraft, keepBoundary, removeBoundary, addBoundary, sectionPayload } =
  await import('../demo/section-draft.js');
const { checkSectionCorrection } = await import('../demo/sections.js');

const markers = () => [{ line: 4, level: 1 }, { line: 10, level: 2 }];

test('an untouched or kept draft saves the shown boundaries unchanged', () => {
  const d = createSectionDraft('doc.md', markers());
  assert.deepEqual(sectionPayload(d), { sections: [{ start_line: 4, level: 1 }, { start_line: 10, level: 2 }] });
  removeBoundary(d, 10);
  keepBoundary(d, 10);
  assert.deepEqual(sectionPayload(d).sections, [{ start_line: 4, level: 1 }, { start_line: 10, level: 2 }]);
});

test('a removed boundary is left out of the payload', () => {
  const d = createSectionDraft('doc.md', markers());
  removeBoundary(d, 4);
  assert.deepEqual(sectionPayload(d).sections, [{ start_line: 10, level: 2 }]);
});

test('an added boundary is sorted in, level 1, never duplicated, and un-removes its line', () => {
  const d = createSectionDraft('doc.md', markers());
  assert.equal(addBoundary(d, 7), true);
  assert.equal(addBoundary(d, 7), true);
  assert.equal(addBoundary(d, 0), true);
  assert.deepEqual(sectionPayload(d).sections.map((s) => s.start_line), [0, 4, 7, 10]);
  assert.equal(sectionPayload(d).sections.find((s) => s.start_line === 7).level, 1);
  removeBoundary(d, 10);
  addBoundary(d, 10); // re-adding a removed shown line restores it (at level 1, as added)
  assert.deepEqual(sectionPayload(d).sections, [
    { start_line: 0, level: 1 }, { start_line: 4, level: 1 }, { start_line: 7, level: 1 }, { start_line: 10, level: 1 }]);
  for (const bad of [-1, 1.5, NaN]) assert.equal(addBoundary(d, bad), false);
  assert.equal(sectionPayload(d).sections.length, 4);
});

test('the Save payload is accepted by the server and stored in the shape intake.py reads', () => {
  const d = createSectionDraft('doc.md', markers());
  removeBoundary(d, 10);
  addBoundary(d, 2);
  const body = JSON.parse(JSON.stringify(sectionPayload(d)));
  assert.deepEqual(Object.keys(body), ['sections']);
  for (const s of body.sections) assert.deepEqual(Object.keys(s).sort(), ['level', 'start_line']);
  const stored = { schema: 1, document: 'doc.md', sections: checkSectionCorrection(body, 20) };
  assert.deepEqual(stored, { schema: 1, document: 'doc.md', sections: [
    { start_line: 2, level: 1, method: 'expert', inferred: false },
    { start_line: 4, level: 1, method: 'expert', inferred: false }] });
});

// UX-01: renderDiff turns service/word_diff.py DiffOp rows into DOM (del/ins), text only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { renderDiff } = await import('../src/index.js');

// Fixture rows generated once by running service/word_diff.py (word_diff) with the project venv
// and pasted here as literals; the diff algorithm is not reimplemented in JS.
const fixtures = [
  { name: 'leading whitespace', original: '  lead the way', candidate: '  led the way', ops: [
    { kind: 'equal', original_text: '  ', candidate_text: '  ' },
    { kind: 'replace', original_text: 'lead ', candidate_text: 'led ' },
    { kind: 'equal', original_text: 'the way', candidate_text: 'the way' }] },
  { name: 'whitespace-only change', original: 'a b', candidate: 'a  b', ops: [
    { kind: 'replace', original_text: 'a ', candidate_text: 'a  ' },
    { kind: 'equal', original_text: 'b', candidate_text: 'b' }] },
  { name: 'empty original', original: '', candidate: 'new words here', ops: [
    { kind: 'insert', original_text: '', candidate_text: 'new words here' }] },
  { name: 'empty candidate', original: 'old words gone', candidate: '', ops: [
    { kind: 'delete', original_text: 'old words gone', candidate_text: '' }] },
];

/** Concatenate text of top-level parts, skipping elements of the excluded tag. */
const side = (el, skip) => [...el.childNodes]
  .filter((n) => !(n.nodeType === 1 && n.tagName.toLowerCase() === skip))
  .map((n) => n.textContent).join('');

for (const f of fixtures) {
  test(`reconstructs both sides: ${f.name}`, () => {
    const el = renderDiff(f.ops);
    assert.equal(side(el, 'ins'), f.original);
    assert.equal(side(el, 'del'), f.candidate);
    for (const n of el.querySelectorAll('del')) assert.equal(n.dataset.kind, 'delete');
    for (const n of el.querySelectorAll('ins')) assert.equal(n.dataset.kind, 'insert');
  });
}

test('replace renders del then ins', () => {
  const el = renderDiff(fixtures[0].ops);
  const tags = [...el.childNodes].map((n) => n.nodeType === 3 ? '#text' : n.tagName.toLowerCase());
  assert.deepEqual(tags, ['#text', 'del', 'ins', '#text']);
});

test('text goes in as text, never HTML', () => {
  // word_diff('see x now', 'see <b>x</b> now')
  const el = renderDiff([
    { kind: 'equal', original_text: 'see ', candidate_text: 'see ' },
    { kind: 'replace', original_text: 'x ', candidate_text: '<b>x</b> ' },
    { kind: 'equal', original_text: 'now', candidate_text: 'now' }]);
  assert.equal(el.querySelector('b'), null);
  assert.equal(el.querySelector('ins').textContent, '<b>x</b> ');
});

test('unknown kind throws', () => {
  assert.throws(() => renderDiff([{ kind: 'move', original_text: 'a', candidate_text: 'a' }]), /kind/);
});

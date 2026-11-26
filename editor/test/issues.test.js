// OV-03: open-issues list. Synthetic fixtures are LLM-built; examples/demo is the shipped synthetic demo.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { openIssues, renderIssues } = await import('../src/issues.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));
const sample1 = JSON.parse(readFileSync(join(dir, 'synthetic-sample-1.moves.json'), 'utf8'));
const ids = genre.moves.map((m) => m.id);

test('(a) sample 1 yields a missing-move issue per absent genre move, in genre order', () => {
  const missing = openIssues(sample1, 10, genre).filter((i) => i.kind === 'missing-move');
  const present = new Set(sample1.map((e) => e.move));
  assert.deepEqual(missing.map((i) => i.moveId), ids.filter((id) => !present.has(id)));
  assert.ok(missing.some((i) => i.moveId === 'gap'));
  assert.match(missing[0].text, /^Missing move: /);
  // all moves absent -> every genre move, genre order
  assert.deepEqual(openIssues([], 0, genre).map((i) => i.moveId), ids);
});

test('(b) one unlabeled issue per run, block = first block of the run', () => {
  const issues = openIssues(sample1, 10, genre);
  const unl = issues.filter((i) => i.kind === 'unlabeled');
  assert.deepEqual(unl.map((i) => i.block), [4]);
  assert.equal(unl[0].text, 'Unlabeled passage');
  assert.equal(issues.at(-1).kind, 'unlabeled', 'missing moves come first');
  const two = openIssues([{ block: 1, move: 'gap' }, { block: 3, move: 'gap' }], 6, genre)
    .filter((i) => i.kind === 'unlabeled').map((i) => i.block);
  assert.deepEqual(two, [0, 2, 4]);
});

test('(c) clicking a block item calls onNavigate with its block', () => {
  const calls = [];
  const ul = renderIssues(document, openIssues(sample1, 10, genre), (b) => calls.push(b));
  const buttons = [...ul.querySelectorAll('button')];
  assert.equal(buttons.length, 1);
  buttons[0].click();
  assert.deepEqual(calls, [4]);
  assert.equal(ul.querySelectorAll('li').length, openIssues(sample1, 10, genre).length);
});

test('(d) no issues renders "No open issues"', () => {
  const all = ids.map((id, block) => ({ block, move: id }));
  assert.deepEqual(openIssues(all, ids.length, genre), []);
  const ul = renderIssues(document, [], () => {});
  assert.equal(ul.textContent, 'No open issues');
  assert.equal(ul.querySelectorAll('button').length, 0);
});

test('(e) unknown move ids are ignored', () => {
  const issues = openIssues([{ block: 0, move: 'nonsense' }, ...ids.slice(1).map((id, i) => ({ block: i + 1, move: id }))],
    ids.length, genre);
  assert.deepEqual(issues.map((i) => [i.kind, i.moveId ?? i.block]), [['missing-move', ids[0]], ['unlabeled', 0]]);
});

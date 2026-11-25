import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as m from '../src/index.js';

const ids = doc => m.buildSidecar(doc).nodes.map(n => n.id);
const oldDoc = text => m.assignIds(m.parseMarkdown(text));
const sidecar = doc => m.parseSidecar(m.serializeSidecar(m.buildSidecar(doc)));

test('unchanged document restores every id by hash without mutating inputs', () => {
  assert.equal(typeof m.reattachIds, 'function');
  const old = oldDoc('# Title\n\n> Quote\n>\n> - one\n> - two\n\n---');
  const doc = m.parseMarkdown('# Title\n\n> Quote\n>\n> - one\n> - two\n\n---');
  const sc = sidecar(old);
  const before = JSON.stringify([doc.toJSON(), old.toJSON(), sc]);
  const result = m.reattachIds(doc, sc);
  assert.deepEqual(ids(result.doc), ids(old));
  assert.deepEqual(result.report, { byHash: ids(old).length, byPath: 0, byFuzzy: 0, fresh: 0 });
  assert.notEqual(result.doc, doc);
  assert.equal(JSON.stringify([doc.toJSON(), old.toJSON(), sc]), before);
});

test('light edits in place retain ids by path after exact matches are reserved', () => {
  const old = oldDoc('red green blue\n\nunchanged');
  const { doc, report } = m.reattachIds(m.parseMarkdown('red green blue gold\n\nunchanged'), sidecar(old));
  assert.deepEqual(ids(doc), ids(old));
  assert.deepEqual(report, { byHash: 1, byPath: 1, byFuzzy: 0, fresh: 0 });
});

test('a moved edited paragraph needs previous text for fuzzy reattachment', () => {
  const old = oldDoc('red green blue\n\nanchor');
  const parsed = m.parseMarkdown('anchor\n\nred green blue gold');
  const sc = sidecar(old);
  const without = m.reattachIds(parsed, sc);
  assert.equal(without.doc.child(0).attrs.id, old.child(1).attrs.id);
  assert.ok(!ids(old).includes(without.doc.child(1).attrs.id));
  assert.deepEqual(without.report, { byHash: 1, byPath: 0, byFuzzy: 0, fresh: 1 });
  const withPrevious = m.reattachIds(parsed, sc, { previousDoc: old });
  assert.deepEqual(ids(withPrevious.doc), ids(old).reverse());
  assert.deepEqual(withPrevious.report, { byHash: 1, byPath: 0, byFuzzy: 1, fresh: 0 });
});

test('reordered paragraphs keep their content ids through the hash pass', () => {
  const old = oldDoc('first\n\nsecond\n\nthird');
  const { doc, report } = m.reattachIds(m.parseMarkdown('third\n\nfirst\n\nsecond'), sidecar(old));
  assert.deepEqual(ids(doc), [ids(old)[2], ids(old)[0], ids(old)[1]]);
  assert.deepEqual(report, { byHash: 3, byPath: 0, byFuzzy: 0, fresh: 0 });
});

test('insertion gets a fresh id after later exact matches claim their ids', () => {
  const old = oldDoc('first\n\nsecond');
  const { doc, report } = m.reattachIds(m.parseMarkdown('new\n\nfirst\n\nsecond'), sidecar(old));
  assert.deepEqual(ids(doc).slice(1), ids(old));
  assert.ok(!ids(old).includes(ids(doc)[0]));
  assert.deepEqual(report, { byHash: 2, byPath: 0, byFuzzy: 0, fresh: 1 });
});

test('deletion does not reuse the deleted id', () => {
  const old = oldDoc('first\n\nsecond\n\nthird');
  const { doc, report } = m.reattachIds(m.parseMarkdown('first\n\nthird'), sidecar(old));
  assert.deepEqual(ids(doc), [ids(old)[0], ids(old)[2]]);
  assert.deepEqual(report, { byHash: 2, byPath: 0, byFuzzy: 0, fresh: 0 });
});

test('duplicate hashes prefer equal paths, then document order, without reuse', () => {
  const old = oldDoc('repeat\n\nanchor\n\nrepeat');
  const { doc, report } = m.reattachIds(m.parseMarkdown('anchor\n\nnew\n\nrepeat\n\nrepeat\n\nrepeat'), sidecar(old));
  assert.equal(ids(doc)[0], ids(old)[1]);
  assert.equal(ids(doc)[2], ids(old)[2]);
  assert.equal(ids(doc)[3], ids(old)[0]);
  assert.equal(new Set(ids(doc)).size, 5);
  assert.deepEqual(report, { byHash: 3, byPath: 0, byFuzzy: 0, fresh: 2 });
});

test('same text in a new type cannot inherit a hash, path or fuzzy match', () => {
  const old = oldDoc('red green blue');
  const { doc, report } = m.reattachIds(m.parseMarkdown('# red green blue'), sidecar(old), { previousDoc: old });
  assert.ok(!ids(old).includes(ids(doc)[0]));
  assert.deepEqual(report, { byHash: 0, byPath: 0, byFuzzy: 0, fresh: 1 });
});

test('fuzzy matching uses token sets, the best score and an inclusive configurable threshold', () => {
  const old = oldDoc('red green\n\nred green blue\n\nanchor');
  // Headings occupy old paragraph paths without being eligible for matching.
  const parsed = m.parseMarkdown('# first\n\n# second\n\nanchor\n\nred red green blue gold');
  const sc = sidecar(old);
  const result = m.reattachIds(parsed, sc, { previousDoc: old, fuzzyThreshold: 0.75 });
  assert.equal(ids(result.doc)[3], ids(old)[1]);
  assert.deepEqual(result.report, { byHash: 1, byPath: 0, byFuzzy: 1, fresh: 2 });
  const strict = m.reattachIds(parsed, sc, { previousDoc: old, fuzzyThreshold: 0.76 });
  assert.ok(!ids(old).includes(ids(strict.doc)[3]));
  assert.equal(strict.report.byFuzzy, 0);
});

test('fuzzy ties use sidecar document order and each candidate is consumed once', () => {
  const old = oldDoc('red green blue\n\nred green gold');
  const parsed = m.parseMarkdown('# first\n\n# second\n\nred green\n\nred green\n\nred green');
  const { doc, report } = m.reattachIds(parsed, sidecar(old), { previousDoc: old });
  assert.deepEqual(ids(doc).slice(2, 4), ids(old));
  assert.ok(!ids(old).includes(ids(doc)[4]));
  assert.deepEqual(report, { byHash: 0, byPath: 0, byFuzzy: 2, fresh: 3 });
});

test('default fuzzy threshold rejects low similarity and missing previous ids', () => {
  const old = oldDoc('red green blue');
  const parsed = m.parseMarkdown('# heading\n\nred green gold silver');
  const rejected = m.reattachIds(parsed, sidecar(old), { previousDoc: old });
  assert.equal(rejected.report.byFuzzy, 0);
  const accepted = m.reattachIds(parsed, sidecar(old), { previousDoc: old, fuzzyThreshold: 0.4 });
  assert.equal(ids(accepted.doc)[1], ids(old)[0]);
  const missing = m.reattachIds(parsed, sidecar(old), { previousDoc: m.parseMarkdown('red green blue'), fuzzyThreshold: 0 });
  assert.equal(missing.report.byFuzzy, 0);
});

test('all id-bearing nested nodes receive unique ids and empty documents are supported', () => {
  const parsed = m.parseMarkdown('> - one\n>   - two\n\n| a | b |\n| - | - |\n| c | d |');
  const before = parsed.toJSON();
  const { doc, report } = m.reattachIds(parsed, sidecar(oldDoc('')));
  const assigned = ids(doc);
  assert.ok(assigned.length > 10);
  assert.ok(assigned.every(id => typeof id === 'string' && id.length > 0));
  assert.equal(new Set(assigned).size, assigned.length);
  assert.equal(report.fresh, assigned.length);
  assert.deepEqual(parsed.toJSON(), before);
  const empty = m.reattachIds(m.parseMarkdown(''), sidecar(oldDoc('')));
  assert.deepEqual(empty.report, { byHash: 0, byPath: 0, byFuzzy: 0, fresh: 0 });
});

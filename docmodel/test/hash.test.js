import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, assignIds, normalizeText, nodeHash, hashText } from '../src/index.js';

const first = (md) => parseMarkdown(md).firstChild;
const h = (md) => nodeHash(first(md));

test('(a) blake3 empty-string vector', () => {
  assert.equal(hashText(''), 'af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262');
  assert.equal(nodeHash(parseMarkdown('')), hashText(''));
});

test('(b) marks do not affect hash', () => {
  const base = h('alpha beta gamma\n');
  for (const md of ['*alpha* beta gamma\n', '**alpha** beta gamma\n',
    '[alpha](http://x.y) beta gamma\n', '`alpha` beta gamma\n', 'alpha ***beta*** gamma\n']) {
    assert.equal(h(md), base, md);
  }
});

test('(c) whitespace and hard-break variants hash equal', () => {
  const base = h('alpha beta gamma\n');
  for (const md of ['alpha   beta\tgamma\n', 'alpha\nbeta\ngamma\n', 'alpha  \nbeta\\\ngamma\n',
    '  alpha beta gamma  \n', 'alpha beta gamma\n']) {
    assert.equal(h(md), base, JSON.stringify(md));
  }
  assert.equal(normalizeText(first('alpha  \nbeta\n')), 'alpha beta');
});

test('(d) different text hashes differ', () => {
  assert.notEqual(h('alpha beta\n'), h('alpha betb\n'));
  assert.notEqual(h('alphabeta\n'), h('alpha beta\n'));
  assert.match(h('x\n'), /^[0-9a-f]{64}$/);
});

test('(e) assignIds does not change per-node hashes', () => {
  const md = '# T\n\npara *x*\n\n- a\n- b\n\n> q\n\n| a | b |\n| - | - |\n| 1 | 2 |\n';
  const before = [];
  const doc = parseMarkdown(md);
  doc.descendants((n) => { before.push(nodeHash(n)); });
  const withIds = assignIds(doc);
  const after = [];
  withIds.descendants((n) => { after.push(nodeHash(n)); });
  assert.notDeepEqual(withIds.firstChild.attrs.id, null);
  assert.deepEqual(after, before);
});

test('(f) em/strong marker and bullet marker do not affect hash', () => {
  assert.equal(h('*a* b\n'), h('_a_ b\n'));
  assert.equal(h('**a** b\n'), h('__a__ b\n'));
  assert.equal(h('- a\n- b\n'), h('* a\n* b\n'));
});

test('(g) node-level hash for paragraph, heading, list_item, table, blockquote', () => {
  assert.equal(normalizeText(first('# Head *x*\n')), 'Head x');
  assert.equal(nodeHash(first('# Head\n')), hashText('Head'));
  const list = first('- one\n- two\n');
  assert.equal(list.firstChild.type.name, 'list_item');
  assert.equal(normalizeText(list.firstChild), 'one');
  assert.equal(nodeHash(list.child(1)), hashText('two'));
  assert.equal(normalizeText(list), 'one two');
  const table = first('| a | b |\n| - | - |\n| 1 | 2 |\n');
  assert.equal(table.type.name, 'table');
  assert.equal(normalizeText(table), 'a b 1 2');
  assert.equal(nodeHash(table), hashText('a b 1 2'));
  const bq = first('> p1\n>\n> p2\n');
  assert.equal(bq.type.name, 'blockquote');
  assert.equal(nodeHash(bq), hashText('p1 p2'));
  assert.equal(nodeHash(first('para\n')), hashText('para'));
});

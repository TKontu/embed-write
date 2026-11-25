// SL-02: span-to-source links survive edits elsewhere and drop when their text is deleted.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState } from 'prosemirror-state';
import { history, undo, redo } from 'prosemirror-history';
import * as api from '../src/index.js';
import { mulberry32 } from './fuzz-gen.js';

const {
  linksPlugin, linksKey, currentLinks, resolveLinks, parseMarkdown, assignIds, openMarkdown,
  buildSidecar, serializeSidecar, parseSidecar, reattachIds,
} = api;
const SEED = 0x51a02;
const FIXTURE = '# Heading here\n\nFirst paragraph with words.\n\nTarget sentence lives here.\n\nThird paragraph text.\n';

const mk = (plugins = []) => EditorState.create({
  doc: assignIds(parseMarkdown(FIXTURE)), plugins: [linksPlugin(), ...plugins],
});
const findText = (doc, s) => {
  let at = -1;
  doc.descendants((n, pos) => { if (at < 0 && n.isText) { const i = n.text.indexOf(s); if (i >= 0) at = pos + i; } });
  assert.ok(at >= 0, `fixture text ${s}`);
  return at;
};
const addLink = (state, from, to, sources = ['src-b', 'src-a']) =>
  state.apply(state.tr.setMeta(linksKey, { add: [{ from, to, sources }] }));
const links = (state) => linksKey.getState(state);
const textOf = (state, l) => state.doc.textBetween(l.from, l.to);
const linked = (state, word = 'sentence lives') => {
  const at = findText(state.doc, word);
  return addLink(state, at, at + word.length);
};

function randomEditOutside(state, span, rnd) {
  const spots = [];
  state.doc.descendants((n, pos) => {
    if (!n.isTextblock) return;
    for (let p = pos + 1; p <= pos + 1 + n.content.size; p++) spots.push({ p, end: pos + 1 + n.content.size });
  });
  const outside = spots.filter((x) => x.p < span.from || x.p > span.to);
  const c = outside[Math.floor(rnd() * outside.length)];
  const tr = state.tr;
  if (rnd() < 0.5) {
    tr.insertText(['x', 'ab', ' word '][Math.floor(rnd() * 3)], c.p);
  } else {
    const hi = c.p < span.from ? Math.min(c.end, span.from) : c.end;
    const b = Math.min(hi, c.p + 1 + Math.floor(rnd() * 3));
    if (b > c.p) tr.delete(c.p, b);
  }
  return tr;
}

test('(a) 100 seeded random edits outside a link keep its text and sources', () => {
  const rnd = mulberry32(SEED);
  let state = linked(mk());
  let changed = 0;
  for (let i = 0; i < 100; i++) {
    const tr = randomEditOutside(state, links(state)[0], rnd);
    if (tr.docChanged) changed++;
    state = state.apply(tr);
    assert.equal(links(state).length, 1, `edit ${i}`);
    assert.equal(textOf(state, links(state)[0]), 'sentence lives', `edit ${i}`);
    assert.deepEqual(links(state)[0].sources, ['src-a', 'src-b']);
  }
  assert.ok(changed > 80, `most edits changed the doc (${changed})`);
});

test('(b) typing strictly inside extends; typing at either boundary stays outside', () => {
  let state = linked(mk());
  let l = links(state)[0];
  state = state.apply(state.tr.insertText('ZZ', l.from + 3));
  assert.equal(textOf(state, links(state)[0]), 'senZZtence lives');
  l = links(state)[0];
  state = state.apply(state.tr.insertText('<', l.from));
  state = state.apply(state.tr.insertText('>', links(state)[0].to));
  assert.equal(textOf(state, links(state)[0]), 'senZZtence lives');
  assert.ok(state.doc.textContent.includes('<senZZtence lives>'));
});

test('(c) deleting the whole span or node drops the link; partial deletion shrinks it', () => {
  let state = linked(mk());
  let l = links(state)[0];
  const partial = state.apply(state.tr.delete(l.from - 3, l.from + 4));
  assert.equal(textOf(partial, links(partial)[0]), 'ence lives');
  const whole = state.apply(state.tr.delete(l.from, l.to));
  assert.deepEqual(links(whole), []);
  const covering = state.apply(state.tr.delete(l.from - 2, l.to + 2));
  assert.deepEqual(links(covering), []);
  const $p = state.doc.resolve(l.from);
  const node = state.apply(state.tr.delete($p.before(), $p.after()));
  assert.deepEqual(links(node), []);
  assert.ok(!node.doc.textContent.includes('Target'));
});

test('(c) splitting a linked textblock clips the link to its first block', () => {
  let state = linked(mk());
  const l = links(state)[0];
  state = state.apply(state.tr.split(l.from + 'sentence'.length));
  assert.equal(textOf(state, links(state)[0]), 'sentence');
});

test('add rejects cross-textblock, empty and source-less spans', () => {
  const state = mk();
  const a = findText(state.doc, 'words');
  const b = findText(state.doc, 'Target');
  for (const add of [{ from: a, to: b + 3, sources: ['s'] }, { from: a, to: a, sources: ['s'] },
    { from: a, to: a + 2, sources: [] }, { from: a, to: a + 2, sources: [''] }]) {
    assert.throws(() => state.apply(state.tr.setMeta(linksKey, { add: [add] })), /links:/);
  }
});

test('remove by sources and clear', () => {
  let state = linked(mk());
  const at = findText(state.doc, 'Third');
  state = addLink(state, at, at + 5, ['other']);
  assert.equal(links(state).length, 2);
  const removed = state.apply(state.tr.setMeta(linksKey, { remove: [{ from: links(state)[0].from, to: links(state)[0].to }] }));
  assert.deepEqual(links(removed).map((l) => l.sources), [['other']]);
  const cleared = state.apply(state.tr.setMeta(linksKey, { clear: true }));
  assert.deepEqual(links(cleared), []);
});

test('(d) undo/redo: typing inside round-trips; undo of a deletion restores text, not the link', () => {
  let state = linked(mk([history()]));
  let l = links(state)[0];
  const dispatch = (tr) => { state = state.apply(tr); };
  dispatch(state.tr.insertText('QQ', l.from + 2));
  assert.equal(textOf(state, links(state)[0]), 'seQQntence lives');
  assert.ok(undo(state, dispatch));
  assert.equal(textOf(state, links(state)[0]), 'sentence lives');
  assert.ok(redo(state, dispatch));
  assert.equal(textOf(state, links(state)[0]), 'seQQntence lives');
  assert.ok(undo(state, dispatch));
  l = links(state)[0];
  dispatch(state.tr.delete(l.from, l.to));
  assert.deepEqual(links(state), []);
  assert.ok(undo(state, dispatch));
  assert.ok(state.doc.textContent.includes('sentence lives'));
  assert.deepEqual(links(state), [], 'undo restores text only; the link stays dropped');
  assert.ok(redo(state, dispatch));
  assert.deepEqual(links(state), []);
});

test('(e) currentLinks -> sidecar -> resolveLinks reopens the same spans and sources', () => {
  let state = linked(mk());
  const h = findText(state.doc, 'Heading');
  state = addLink(state, h, h + 7, ['h1']);
  state = state.apply(state.tr.insertText('new ', findText(state.doc, 'First')));
  const entries = currentLinks(state);
  assert.deepEqual(entries.map((e) => Object.keys(e)), entries.map(() => ['node', 'from', 'to', 'sources']));
  const sidecar = parseSidecar(serializeSidecar({ ...buildSidecar(state.doc), links: entries }));
  const md = api.serializeMarkdown(state.doc);
  const opened = openMarkdown(md);
  assert.equal(opened.readOnly, false);
  const { doc } = reattachIds(opened.doc, sidecar);
  const { links: resolved, skipped } = resolveLinks(doc, sidecar.links);
  assert.deepEqual(skipped, []);
  let fresh = EditorState.create({ doc, plugins: [linksPlugin()] });
  fresh = fresh.apply(fresh.tr.setMeta(linksKey, { add: resolved }));
  const view = (s) => links(s).map((l) => [textOf(s, l), l.sources]);
  assert.deepEqual(view(fresh), view(state));
  assert.deepEqual(currentLinks(fresh), entries);
});

test('resolveLinks skips and reports missing nodes and out-of-range offsets', () => {
  const state = mk();
  let id;
  state.doc.descendants((n) => { if (!id && n.type.name === 'paragraph') id = n.attrs.id; });
  const good = { node: id, from: 0, to: 5, sources: ['s'] };
  const { links: out, skipped } = resolveLinks(state.doc, [good, { ...good, node: 'nope' }, { ...good, to: 999 }]);
  assert.equal(out.length, 1);
  assert.equal(state.doc.textBetween(out[0].from, out[0].to), 'First');
  assert.deepEqual(skipped.map((s) => s.index), [1, 2]);
  assert.ok(skipped.every((s) => typeof s.reason === 'string'));
});

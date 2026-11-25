// PM-01: overlay positions survive transactions.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState } from 'prosemirror-state';
import { history, undo, redo } from 'prosemirror-history';
import { canSplit, canJoin } from 'prosemirror-transform';
import * as api from '../src/index.js';
import { mulberry32 } from './fuzz-gen.js';

const { overlayPlugin, overlayKey, overlayRanges, parseMarkdown } = api;
const SEED = 0x9e3779b1;
const FIXTURE = 'First paragraph with words.\n\nTarget sentence lives here.\n\nThird paragraph text.\n\nFourth one.\n';

const mk = (plugins = []) => EditorState.create({ doc: parseMarkdown(FIXTURE), plugins: [overlayPlugin(), ...plugins] });
const findText = (doc, s) => {
  let at = -1;
  doc.descendants((n, pos) => { if (at < 0 && n.isText) { const i = n.text.indexOf(s); if (i >= 0) at = pos + i; } });
  return at;
};
const addOverlay = (state, from, to, spec = { kind: 'test' }) =>
  state.apply(state.tr.setMeta(overlayKey, { add: [{ from, to, spec }] }));
const textblockPositions = (doc) => {
  const out = [];
  doc.descendants((n, pos) => { if (n.isTextblock) for (let p = pos + 1; p <= pos + 1 + n.content.size; p++) out.push({ p, start: pos + 1, end: pos + 1 + n.content.size }); });
  return out;
};

function randomEditOutside(state, span, rnd) {
  const { from, to } = span;
  const outside = textblockPositions(state.doc).filter((x) => x.p < from || x.p > to);
  const pick = (a) => a[Math.floor(rnd() * a.length)];
  const kind = Math.floor(rnd() * 4);
  const tr = state.tr;
  if (kind === 0) {
    tr.insertText(pick(['x', 'ab', ' word ']), pick(outside).p);
  } else if (kind === 1) {
    const c = pick(outside);
    const hi = c.p < from ? Math.min(c.end, from - 1) : c.end; // stay in one textblock, never reach the span
    const b = Math.min(hi, c.p + 1 + Math.floor(rnd() * 3));
    if (b > c.p) tr.delete(c.p, b);
  } else if (kind === 2) {
    const c = pick(outside);
    if (canSplit(tr.doc, c.p)) tr.split(c.p);
  } else {
    const joins = [];
    tr.doc.descendants((n, pos) => { if (pos > 0 && canJoin(tr.doc, pos)) joins.push(pos); });
    if (joins.length) tr.join(pick(joins));
  }
  return tr;
}

test('(a)+(b)+(e) overlay covers the same text after 100 seeded random edits outside it', () => {
  const rnd = mulberry32(SEED);
  let state = mk();
  const at = findText(state.doc, 'sentence lives');
  const want = 'sentence lives';
  state = addOverlay(state, at, at + want.length);
  let edits = 0;
  for (let i = 0; i < 100; i++) {
    const [span] = overlayRanges(state);
    const before = span.from;
    const tr = randomEditOutside(state, span, rnd);
    if (tr.docChanged) edits++;
    state = state.apply(tr);
    const ranges = overlayRanges(state);
    assert.equal(ranges.length, 1, `seed=${SEED} step=${i}: overlay lost`);
    const r = ranges[0];
    assert.equal(state.doc.textBetween(r.from, r.to), want, `seed=${SEED} step=${i}: overlay text drifted`);
    assert.equal(r.from, tr.mapping.map(before, 1), `seed=${SEED} step=${i}: position not mapped`);
  }
  assert.ok(edits >= 50, `seed=${SEED}: only ${edits} effective edits`);
});

test('(b) edits before the span shift positions, text unchanged', () => {
  let state = mk();
  const at = findText(state.doc, 'Target');
  state = addOverlay(state, at, at + 6);
  state = state.apply(state.tr.insertText('PREFIX ', 1));
  const [r] = overlayRanges(state);
  assert.equal(r.from, at + 7);
  assert.equal(state.doc.textBetween(r.from, r.to), 'Target');
  state = state.apply(state.tr.delete(1, 4));
  const [r2] = overlayRanges(state);
  assert.equal(r2.from, at + 4);
  assert.equal(state.doc.textBetween(r2.from, r2.to), 'Target');
});

test('(c) deleting the whole span drops the decoration', () => {
  let state = mk();
  const at = findText(state.doc, 'Target');
  state = addOverlay(state, at, at + 6);
  state = state.apply(state.tr.delete(at - 1, at + 8));
  assert.deepEqual(overlayRanges(state), []);
});

test('(d) setMeta add/clear, sorted ranges, undo/redo with prosemirror-history', () => {
  let state = mk([history()]);
  const a = findText(state.doc, 'Third');
  const b = findText(state.doc, 'First');
  state = state.apply(state.tr.setMeta(overlayKey, { add: [{ from: a, to: a + 5, spec: { k: 2 } }, { from: b, to: b + 5, spec: { k: 1 } }] }));
  assert.deepEqual(overlayRanges(state).map((r) => r.spec.k), [1, 2]);
  state = state.apply(state.tr.insertText('zz', b));
  const dispatch = (tr) => { state = state.apply(tr); };
  assert.ok(undo(state, dispatch));
  assert.equal(state.doc.textBetween(overlayRanges(state)[0].from, overlayRanges(state)[0].to), 'First');
  assert.ok(redo(state, dispatch));
  for (const r of overlayRanges(state)) assert.match(state.doc.textBetween(r.from, r.to), /^(First|Third)$/);
  state = state.apply(state.tr.setMeta(overlayKey, { clear: true }));
  assert.deepEqual(overlayRanges(state), []);
  assert.ok(undo(state, dispatch));
  assert.ok(Array.isArray(overlayRanges(state)));
});

// HS-04: incremental dirty sets stay correct under random edits interleaved with undo/redo.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState } from 'prosemirror-state';
import { history, undo, redo } from 'prosemirror-history';
import { canSplit, canJoin } from 'prosemirror-transform';
import * as model from '../src/index.js';

const SEQUENCES = 200;
const STEPS = 24;
const FIXTURE = [
  '# Title', '', 'Intro paragraph with *some* text.', '',
  '## Section', '', '- first item', '- second **bold** item', '  - nested item', '',
  '> quoted line one', '>', '> quoted line two', '',
  '```', 'code block', '```', '', 'Closing paragraph here.', '',
].join('\n');

// mulberry32: small deterministic PRNG, no dependency.
function prng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const idMap = (doc) => {
  const map = new Map();
  doc.descendants((node) => { if (node.attrs.id != null) map.set(node.attrs.id, node); });
  return map;
};

/** Full recompute: after-doc ids whose node differs from the before doc, plus id-bearing ancestors. */
function recompute(beforeDoc, afterDoc) {
  const before = idMap(beforeDoc);
  const result = new Set();
  const walk = (node, ancestors) => {
    const id = node.attrs.id;
    let next = ancestors;
    if (id != null) {
      if (!before.get(id)?.eq(node)) { result.add(id); ancestors.forEach((a) => result.add(a)); }
      next = [...ancestors, id];
    }
    node.forEach((child) => walk(child, next));
  };
  walk(afterDoc, []);
  return result;
}

const textblocks = (doc) => {
  const out = [];
  doc.descendants((node, pos) => { if (node.isTextblock) out.push({ node, pos }); });
  return out;
};
const pick = (rand, list) => list[Math.floor(rand() * list.length)];
const posIn = (rand, { node, pos }) => pos + 1 + Math.floor(rand() * (node.content.size + 1));

/** Build one random edit transaction, or null when the chosen edit is not applicable. */
function randomEdit(rand, state) {
  const { doc } = state;
  const tr = state.tr;
  const blocks = textblocks(doc);
  const kind = Math.floor(rand() * 6);
  if (kind === 0) {
    const at = posIn(rand, pick(rand, blocks));
    tr.insertText(pick(rand, ['x', 'yz', ' word ']), at);
  } else if (kind === 1) {
    const a = 1 + Math.floor(rand() * (doc.content.size - 1));
    const b = Math.min(doc.content.size, a + 1 + Math.floor(rand() * 12));
    tr.delete(a, b);
  } else if (kind === 2) {
    const at = posIn(rand, pick(rand, blocks));
    const depth = 1 + (rand() < 0.3 ? 1 : 0);
    if (!canSplit(doc, at, depth)) return null;
    tr.split(at, depth);
  } else if (kind === 3) {
    const { pos } = pick(rand, blocks);
    // pos is the boundary before this textblock; join it with its previous sibling.
    if (!canJoin(doc, pos)) return null;
    tr.join(pos);
  } else if (kind === 4) {
    const b = pick(rand, blocks.filter((x) => x.node.type.spec.marks !== ''));
    if (!b || !b.node.content.size) return null;
    const from = posIn(rand, b);
    const to = Math.min(b.pos + 1 + b.node.content.size, from + 1 + Math.floor(rand() * 6));
    if (to <= from) return null;
    const mark = doc.type.schema.marks[pick(rand, ['em', 'strong'])].create();
    if (doc.rangeHasMark(from, to, mark.type)) tr.removeMark(from, to, mark.type);
    else tr.addMark(from, to, mark);
  } else {
    if (doc.childCount < 2) return null;
    const i = Math.floor(rand() * doc.childCount);
    let start = 0;
    for (let k = 0; k < i; k++) start += doc.child(k).nodeSize;
    const node = doc.child(i);
    tr.delete(start, start + node.nodeSize);
    const target = Math.floor(rand() * tr.doc.childCount + 1);
    let at = 0;
    for (let k = 0; k < target; k++) at += tr.doc.child(k).nodeSize;
    tr.insert(at, node);
  }
  return tr.docChanged ? tr : null;
}

/** Run one seeded sequence; dirtyFn lets the broken-implementation demo swap dirtySet. */
function runSequence(seed, dirtyFn = model.dirtySet) {
  const rand = prng(seed);
  let counter = 0;
  const opts = { now: () => 1700000000000 + counter++, rand: (buf) => buf.map(() => Math.floor(rand() * 256)) };
  let state = EditorState.create({
    doc: model.assignIds(model.parseMarkdown(FIXTURE), opts),
    plugins: [model.idPlugin(opts), history()],
  });
  const firstDoc = state.doc;
  const flushed = new Set();
  const coalescer = model.createCoalescer({
    delayMs: 1000, onFlush: ({ ids }) => ids.forEach((id) => flushed.add(id)),
    now: () => 0, setTimer: () => ({}), clearTimer: () => {},
  });
  let checked = 0;
  let step = 0;
  const where = () => `seed=${seed} step=${step}`;
  const apply = (tr) => {
    const result = state.applyTransaction(tr);
    for (const t of result.transactions) {
      const incremental = dirtyFn(t);
      const expected = recompute(t.before, t.doc);
      const after = idMap(t.doc);
      for (const id of expected) assert.ok(incremental.has(id), `${where()}: missing dirty id ${id}`);
      for (const id of incremental) assert.ok(after.has(id), `${where()}: foreign id ${id}`);
      coalescer.add(t);
      checked++;
    }
    state = result.state;
  };
  for (; step < STEPS; step++) {
    const r = rand();
    if (r < 0.2) undo(state, apply);
    else if (r < 0.3) redo(state, apply);
    else {
      let tr = null;
      for (let tries = 0; !tr && tries < 10; tries++) {
        try { tr = randomEdit(rand, state); } catch { tr = null; }
      }
      if (tr) apply(tr);
    }
  }
  coalescer.flush();
  for (const id of recompute(firstDoc, state.doc)) {
    assert.ok(flushed.has(id), `seed=${seed} final: coalescer union misses ${id}`);
  }
  return checked;
}

test(`dirtySet covers a full recompute across ${SEQUENCES} seeded edit/undo/redo sequences`, () => {
  let transactions = 0;
  for (let seed = 1; seed <= SEQUENCES; seed++) transactions += runSequence(seed);
  // Sanity: the generator really exercises transactions, not skipped steps.
  assert.ok(transactions > SEQUENCES * STEPS * 0.5, `only ${transactions} transactions checked`);
});

test('the property detects a broken dirtySet', () => {
  assert.throws(() => {
    for (let seed = 1; seed <= 5; seed++) runSequence(seed, () => new Set());
  }, /seed=\d+ step=\d+: missing dirty id/);
});

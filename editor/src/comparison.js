// @ts-check
// OV-02 (D-009 slice): comparison strip — the typical move order for this section type beside the
// draft's. In the thin demo the "corpus" is the synthetic, LLM-built sample set in examples/demo and
// the whole document is one section type. The typical order is built explainably from transition
// statistics (architecture: sequence model, transition statistics first). Colours come only from
// legendCss rules keyed on data-signal-kind (I3); the caption says pattern fit, not a verdict (I8).
// Production caller: editor/demo/app.js; AP-01 wires it in the app. O(samples x moves).
import { renderMinimap } from './minimap.js';

/**
 * @typedef {{ from: string | null, to: string, count: number, of: number }} SequenceStep
 * `from` is null for the first step (count = samples starting with `to`, of = all samples).
 */

/**
 * Collapse a moves.json label list into its run sequence of move ids, in block order.
 * @param {Array<{ block: number, move: string }>} moves
 * @returns {string[]}
 */
export function moveSequence(moves) {
  const sorted = [...(moves ?? [])].filter((e) => Number.isInteger(e.block))
    .sort((a, b) => a.block - b.block);
  /** @type {string[]} */
  const out = [];
  for (const e of sorted) if (out[out.length - 1] !== e.move) out.push(e.move);
  return out;
}

/**
 * Typical sequence: the most common first move, then repeatedly the most frequent observed next
 * move not yet used; ties break by `order` (genre order), then id. Stops when no transition remains.
 * @param {string[][]} sequences
 * @param {string[]} [order] genre move ids, for tie-breaking
 * @returns {{ sequence: string[], support: SequenceStep[] }}
 */
export function typicalSequence(sequences, order = []) {
  const seqs = (sequences ?? []).filter((s) => s.length);
  const rank = (/** @type {string} */ id) => { const i = order.indexOf(id); return i < 0 ? order.length : i; };
  /** @param {Map<string, number>} counts @param {Set<string>} used */
  const best = (counts, used) => {
    const c = [...counts].filter(([id]) => !used.has(id));
    c.sort((a, b) => b[1] - a[1] || rank(a[0]) - rank(b[0]) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    return c[0];
  };
  /** @type {Map<string, number>} */
  const firsts = new Map();
  /** @type {Map<string, Map<string, number>>} samples with transition from -> to */
  const trans = new Map();
  /** @type {Map<string, number>} samples containing a move */
  const contains = new Map();
  for (const s of seqs) {
    firsts.set(s[0], (firsts.get(s[0]) ?? 0) + 1);
    for (const id of new Set(s)) contains.set(id, (contains.get(id) ?? 0) + 1);
    const pairs = new Set();
    for (let i = 1; i < s.length; i += 1) pairs.add(JSON.stringify([s[i - 1], s[i]]));
    for (const p of pairs) {
      const [from, to] = JSON.parse(p);
      if (!trans.has(from)) trans.set(from, new Map());
      const m = /** @type {Map<string, number>} */ (trans.get(from));
      m.set(to, (m.get(to) ?? 0) + 1);
    }
  }
  const used = new Set();
  /** @type {SequenceStep[]} */
  const support = [];
  const first = best(firsts, used);
  if (!first) return { sequence: [], support };
  used.add(first[0]);
  support.push({ from: null, to: first[0], count: first[1], of: seqs.length });
  let current = first[0];
  for (;;) {
    const next = best(trans.get(current) ?? new Map(), used);
    if (!next) break;
    support.push({ from: current, to: next[0], count: next[1], of: contains.get(current) ?? 0 });
    used.add(next[0]);
    current = next[0];
  }
  return { sequence: support.map((s) => s.to), support };
}

/** @param {string[]} sequence */
const asSegments = (sequence) => sequence.map((move, start) => ({ move, start, count: 1 }));

/**
 * Two labelled strips (draft, typical) with one caption per typical step. Reuses minimap markup.
 * @param {Document} doc
 * @param {{ draft: string[], typical: { sequence: string[], support: SequenceStep[] }, genre: any, samples?: number }} input
 * @returns {HTMLElement}
 */
export function renderComparison(doc, { draft, typical, genre, samples }) {
  const ids = new Set((genre?.moves ?? []).map((/** @type {any} */ m) => m.id));
  const names = new Map((genre?.moves ?? []).map((/** @type {any} */ m) => [m.id, m.name ?? m.id]));
  const known = (/** @type {string} */ id) => (ids.size && !ids.has(id) ? 'other' : id);
  const name = (/** @type {string} */ id) => names.get(id) ?? id;
  const n = samples ?? typical.support[0]?.of ?? 0;
  const root = doc.createElement('section');
  root.className = 'comparison';
  /** @param {string} label @param {string[]} seq @param {string} kind */
  const row = (label, seq, kind) => {
    const wrap = doc.createElement('div');
    wrap.className = `comparison-row comparison-${kind}`;
    const l = doc.createElement('div');
    l.className = 'comparison-label';
    l.textContent = label;
    const strip = renderMinimap(doc, asSegments(seq.map(known)), genre);
    strip.setAttribute('aria-label', `${label}: move sequence`);
    wrap.append(l, strip);
    return wrap;
  };
  root.append(row('This draft', draft, 'draft'),
    row(`Typical sequence (${n} synthetic sample${n === 1 ? '' : 's'}, LLM-built)`, typical.sequence, 'typical'));
  const list = doc.createElement('ol');
  list.className = 'comparison-steps';
  for (const s of typical.support) {
    const li = doc.createElement('li');
    li.textContent = s.from === null
      ? `${name(s.to)} comes first in ${s.count} of ${s.of} samples`
      : `${name(s.to)} follows ${name(s.from)} in ${s.count} of ${s.of} samples`;
    list.append(li);
  }
  const note = doc.createElement('p');
  note.className = 'comparison-note';
  note.textContent = 'Pattern fit, not a verdict.';
  root.append(list, note);
  return root;
}

/**
 * Demo wiring: draft strip from the loaded sample's labels, typical strip from all samples.
 * @param {HTMLElement} mount
 * @param {Array<{ block: number, move: string }>} draftMoves
 * @param {Array<Array<{ block: number, move: string }>>} sampleMoves
 * @param {any} genre
 */
export function mountComparison(mount, draftMoves, sampleMoves, genre) {
  const order = (genre?.moves ?? []).map((/** @type {any} */ m) => m.id);
  const seqs = sampleMoves.map(moveSequence);
  const typical = typicalSequence(seqs, order);
  mount.replaceChildren(renderComparison(mount.ownerDocument,
    { draft: moveSequence(draftMoves), typical, genre, samples: seqs.length }));
}

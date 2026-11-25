// @ts-check
// SL-02: span-to-source links. A span of text in one textblock carries a set of source item ids.
// Unwired by design: ED-01 wires linksPlugin into the editor and sidecar save/open;
// BH-06/generation write sources via the plugin meta.
//
// Rules:
// - Confinement: a link lives inside exactly one id-bearing textblock. `add` throws on a span
//   crossing textblock boundaries. If a later split puts the link's ends in different
//   textblocks, it is clipped to the end of the block holding `from`.
// - Mapping (assoc): `from` maps with assoc +1 and `to` with assoc -1, so text typed exactly at
//   either boundary falls outside the link; text typed strictly inside extends it.
// - Deletion: a link whose span collapses to empty (all its text deleted, or its node deleted)
//   is dropped. Partial deletion shrinks it.
// - Undo/redo: plugin state is only ever the mapped result. Undo of a deletion restores the
//   text but NOT a dropped link (dropping is final); undo of an insertion inside a link maps
//   it back to its old extent.
// Cost: apply is O(links) per transaction; currentLinks resolves each link (no doc walk beyond
// that); resolveLinks walks the doc once. Large-doc cost is unmeasured.
import { Plugin, PluginKey } from 'prosemirror-state';

/** @typedef {{from: number, to: number, sources: string[]}} Link */
/** @typedef {import('prosemirror-model').Node} PMNode */

export const linksKey = new PluginKey('links');

/** @param {unknown} sources @returns {string[]} */
function canonicalSources(sources) {
  if (!Array.isArray(sources) || sources.length === 0 ||
      !sources.every((s) => typeof s === 'string' && s.length > 0)) {
    throw new Error('links: sources must be a non-empty array of non-empty strings');
  }
  return [...new Set(sources)].sort();
}

/** @param {PMNode} doc @param {number} pos */
function textblockAt(doc, pos) {
  const $pos = doc.resolve(pos);
  return $pos.parent.isTextblock ? { node: $pos.parent, start: $pos.start(), end: $pos.end() } : null;
}

/** @param {PMNode} doc @param {any} raw @returns {Link} */
function validLink(doc, raw) {
  const { from, to } = raw ?? {};
  if (!Number.isSafeInteger(from) || !Number.isSafeInteger(to) || from < 0 || to <= from || to > doc.content.size) {
    throw new Error('links: add needs integer positions with from < to inside the document');
  }
  const block = textblockAt(doc, from);
  if (!block || to > block.end) throw new Error('links: a link must stay inside one textblock');
  if (block.node.attrs.id == null) throw new Error('links: textblock has no id; run assignIds first');
  return { from, to, sources: canonicalSources(raw.sources) };
}

/** @param {Link} a @param {Link} b */
const order = (a, b) => a.from - b.from || a.to - b.to ||
  (a.sources.join('\u0000') < b.sources.join('\u0000') ? -1 : a.sources.join('\u0000') > b.sources.join('\u0000') ? 1 : 0);

/**
 * Plugin state: Link[] with absolute positions in the current doc, sorted by from, to, sources.
 * Meta (tr.setMeta(linksKey, ...)), positions referring to tr.doc, applied in this order:
 *   { clear?: boolean, remove?: Array<{from:number, to:number}>, add?: Array<{from, to, sources}> }
 * `remove` drops links with exactly that from/to. Invalid `add` entries throw.
 * @returns {Plugin}
 */
export function linksPlugin() {
  return new Plugin({
    key: linksKey,
    state: {
      init: () => [],
      apply(tr, /** @type {Link[]} */ prev) {
        /** @type {Link[]} */
        let next = prev;
        if (tr.docChanged) {
          next = [];
          for (const link of prev) {
            const from = tr.mapping.map(link.from, 1);
            let to = tr.mapping.map(link.to, -1);
            if (to <= from) continue;
            const block = textblockAt(tr.doc, from);
            if (!block) continue;
            if (to > block.end) to = block.end;
            if (to > from) next.push({ from, to, sources: link.sources });
          }
        }
        const meta = tr.getMeta(linksKey);
        if (meta) {
          if (meta.clear) next = [];
          if (meta.remove?.length) {
            const gone = new Set(meta.remove.map((r) => `${r.from}:${r.to}`));
            next = next.filter((l) => !gone.has(`${l.from}:${l.to}`));
          }
          if (meta.add?.length) next = [...next, ...meta.add.map((raw) => validLink(tr.doc, raw))];
        }
        return next === prev ? prev : next.sort(order);
      },
    },
  });
}

/**
 * Sidecar-shaped links: node id plus character offsets within that node's text content.
 * Sorted by document position, then to, then sources.
 * @param {import('prosemirror-state').EditorState} state
 * @returns {import('./sidecar.js').SidecarLink[]}
 */
export function currentLinks(state) {
  /** @type {Link[]} */
  const list = linksKey.getState(state) ?? [];
  return list.flatMap((l) => {
    const block = textblockAt(state.doc, l.from);
    if (!block || block.node.attrs.id == null) return [];
    const offset = (/** @type {number} */ pos) => state.doc.textBetween(block.start, pos, undefined, '￼').length;
    return [{ node: block.node.attrs.id, from: offset(l.from), to: offset(l.to), sources: [...l.sources] }];
  });
}

/**
 * Absolute positions for sidecar links in doc (e.g. after reattachIds), ready for
 * tr.setMeta(linksKey, {add: links}). Entries whose node id is missing or whose offsets
 * exceed the node's text are skipped and reported by index.
 * @param {PMNode} doc
 * @param {import('./sidecar.js').SidecarLink[]} entries
 * @returns {{links: Link[], skipped: Array<{index: number, reason: string}>}}
 */
export function resolveLinks(doc, entries) {
  /** @type {Map<string, number>} */
  const starts = new Map();
  doc.descendants((node, pos) => {
    if (node.isTextblock && node.attrs.id != null && !starts.has(node.attrs.id)) starts.set(node.attrs.id, pos + 1);
    return !node.isTextblock;
  });
  /** @type {Link[]} */
  const links = [];
  const skipped = [];
  entries.forEach((entry, index) => {
    const start = starts.get(entry.node);
    if (start === undefined) { skipped.push({ index, reason: `node ${entry.node} not found` }); return; }
    const block = doc.resolve(start).parent;
    // Map text offsets to positions; non-text inline leaves count as one character.
    /** @type {number[]} */
    const posAt = [];
    block.forEach((child, off) => {
      const len = child.isText ? child.text?.length ?? 0 : 1;
      for (let i = 0; i < len; i++) posAt.push(start + off + i);
    });
    posAt.push(start + block.content.size);
    if (entry.to >= posAt.length) {
      skipped.push({ index, reason: `offsets ${entry.from}-${entry.to} exceed node text length ${posAt.length - 1}` });
      return;
    }
    links.push({ from: posAt[entry.from], to: posAt[entry.to], sources: [...entry.sources] });
  });
  return { links, skipped };
}

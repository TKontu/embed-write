// @ts-check
/** HS-02. Unwired by design; HS-03/HS-04 and ED-01 consume these helpers. */

/**
 * Changed ranges from step maps, in final-document coordinates. Touching ranges
 * are merged; deletions remain zero-width ranges. Mark-only steps have no map.
 * @param {import('prosemirror-transform').Transform} tr
 * @returns {{from: number, to: number}[]}
 */
export function dirtyRanges(tr) {
  const ranges = [];
  tr.mapping.maps.forEach((map, i) => {
    const rest = tr.mapping.slice(i + 1);
    map.forEach((_a, _b, from, to) => {
      const start = rest.map(from, -1);
      const end = rest.map(to, 1);
      ranges.push({ from: Math.min(start, end), to: Math.max(start, end) });
    });
  });
  ranges.sort((a, b) => a.from - b.from || a.to - b.to);
  const merged = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range.from <= last.to) last.to = Math.max(last.to, range.to);
    else merged.push({ ...range });
  }
  return merged;
}

/**
 * Final node ids whose nodes differ from the initial document, plus ancestors.
 * Equality includes attrs and marks: mark-only edits dirty the containing block,
 * even though HS-01 hashes ignore marks (callers may compare hashes afterward).
 * Null-id nodes are represented by their nearest id-bearing ancestor.
 *
 * Scale residual: building the initial id index costs O(document nodes) memory
 * and time. Equality may visit changed subtrees; this is not yet a strictly
 * range/depth-bounded implementation. Unchanged persistent subtrees compare by
 * identity. IDs are expected to be unique, as provided by NI-01 assignIds.
 * @param {import('prosemirror-transform').Transform} tr
 * @returns {Set<string>}
 */
export function dirtySet(tr) {
  const result = new Set();
  if (!tr.steps.length) return result;
  const before = new Map();
  tr.before.descendants(node => {
    if (node.attrs.id != null) before.set(node.attrs.id, node);
  });
  // Inspect persistent subtrees once. Pruning equal id-bearing nodes avoids
  // traversing untouched siblings, including those touching deletion boundaries.
  const walk = (node, ancestors) => {
    const id = node.attrs.id;
    if (id != null) {
      if (before.get(id)?.eq(node)) return;
      result.add(id);
      for (const ancestor of ancestors) result.add(ancestor);
      ancestors = [...ancestors, id];
    }
    node.forEach(child => walk(child, ancestors));
  };
  walk(tr.doc, []);
  return result;
}

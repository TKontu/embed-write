// @ts-check
// NI-03: unwired by design; ED-01 wires reattachment into document open.
import { Fragment } from 'prosemirror-model';
import { assignIds } from './ids.js';
import { nodeHash, normalizeText } from './hash.js';

/**
 * Restore ids on a freshly parsed document from a parsed version-1 sidecar.
 * Inputs are immutable; only nodes declaring an id attribute participate.
 * Hash, path, then optional fuzzy matching each run across the whole document.
 * Sidecar entries are in document order (as emitted by buildSidecar).
 * Hash/path indexing is O(nodes), excluding hashing text and constructing paths;
 * each queue entry is visited at most once. Fuzzy matching compares every unmatched
 * new/old pair of the same type, with token-set intersection work per pair. Memory
 * holds one document's indexes and token sets; this is not a corpus operation.
 * Empty token sets have similarity 1; words are case-sensitive, whitespace-delimited.
 * No file I/O. The default fuzzy threshold is 0.6, inclusive.
 * @param {import('prosemirror-model').Node} doc
 * @param {import('./sidecar.js').Sidecar} sidecar
 * @param {{previousDoc?: import('prosemirror-model').Node, fuzzyThreshold?: number}} [opts]
 */
export function reattachIds(doc, sidecar, opts = {}) {
  const report = { byHash: 0, byPath: 0, byFuzzy: 0, fresh: 0 };
  const used = new Set();
  const matches = new Map();
  const nodes = [];
  const walk = (node, path) => {
    if (Object.hasOwn(node.attrs, 'id')) nodes.push({ node, path: path.join('/') });
    node.forEach((child, offset, index) => walk(child, [...path, index]));
  };
  walk(doc, []);
  const paths = new Map();
  const hashes = new Map();
  const hashPaths = new Map();
  const add = (map, key, entry) => {
    if (!map.has(key)) map.set(key, { entries: [], next: 0 });
    map.get(key).entries.push(entry);
  };
  for (const entry of sidecar.nodes) {
    const key = `${entry.type}:${entry.hash}`;
    add(paths, `${entry.type}:${entry.path.join('/')}`, entry);
    add(hashes, key, entry);
    add(hashPaths, `${key}:${entry.path.join('/')}`, entry);
  }
  const take = (map, key) => {
    const queue = map.get(key);
    if (!queue) return;
    while (queue.next < queue.entries.length) {
      const entry = queue.entries[queue.next++];
      if (!used.has(entry.id)) return entry;
    }
  };
  const match = (item, entry, pass) => {
    matches.set(item.node, entry.id);
    used.add(entry.id);
    report[pass]++;
  };
  for (const item of nodes) {
    const key = `${item.node.type.name}:${nodeHash(item.node)}`;
    const entry = take(hashPaths, `${key}:${item.path}`) ?? take(hashes, key);
    if (entry) match(item, entry, 'byHash');
  }
  for (const item of nodes) {
    if (matches.has(item.node)) continue;
    const entry = take(paths, `${item.node.type.name}:${item.path}`);
    if (entry) match(item, entry, 'byPath');
  }
  if (opts.previousDoc) {
    const previous = new Map();
    opts.previousDoc.descendants(node => {
      if (Object.hasOwn(node.attrs, 'id')) previous.set(node.attrs.id, node);
    });
    const tokens = node => new Set(normalizeText(node).split(' ').filter(Boolean));
    const candidates = new Map();
    for (const entry of sidecar.nodes) {
      const node = previous.get(entry.id);
      if (used.has(entry.id) || !node || node.type.name !== entry.type) continue;
      if (!candidates.has(entry.type)) candidates.set(entry.type, []);
      candidates.get(entry.type).push({ entry, words: tokens(node) });
    }
    for (const item of nodes) {
      if (matches.has(item.node)) continue;
      const words = tokens(item.node);
      let best;
      let bestScore = -1;
      for (const candidate of candidates.get(item.node.type.name) ?? []) {
        if (used.has(candidate.entry.id)) continue;
        let intersection = 0;
        for (const word of words) if (candidate.words.has(word)) intersection++;
        const union = words.size + candidate.words.size - intersection;
        const score = union === 0 ? 1 : intersection / union;
        if (score >= (opts.fuzzyThreshold ?? 0.6) && score > bestScore) {
          best = candidate.entry;
          bestScore = score;
        }
      }
      if (best) match(item, best, 'byFuzzy');
    }
  }
  report.fresh = nodes.length - matches.size;
  const rebuild = node => {
    if (node.isText) return node;
    const children = [];
    node.forEach(child => children.push(rebuild(child)));
    const attrs = Object.hasOwn(node.attrs, 'id')
      ? { ...node.attrs, id: matches.get(node) ?? null } : node.attrs;
    return node.type.create(attrs, Fragment.fromArray(children), node.marks);
  };
  return { doc: assignIds(rebuild(doc)), report };
}

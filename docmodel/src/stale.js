// @ts-check
// PM-02: stale-result policy. An analysis result `{nodeId, hash, ...}` is fresh only when a node
// with `nodeId` exists in the doc and `nodeHash(node) === result.hash`; otherwise it is discarded
// ('missing' | 'changed' | 'malformed'), never drawn. Mark-only edits keep results fresh because
// nodeHash ignores marks (HS-01). Pure; no rendering.
// Unwired by design: ED-01 and the overlay rows (PM-01) wire it.
import { nodeHash } from './hash.js';

/** @typedef {'missing' | 'changed' | 'malformed'} DiscardReason */

/** @param {unknown} r @returns {r is {nodeId: string, hash: string}} */
function wellFormed(r) {
  if (r === null || typeof r !== 'object') return false;
  const { nodeId, hash } = /** @type {any} */ (r);
  return typeof nodeId === 'string' && nodeId !== '' && typeof hash === 'string';
}

/**
 * Lazy hash lookup over one doc walk: id -> node is indexed once; nodeHash is computed only for
 * ids that results reference, at most once per node.
 * @param {import('prosemirror-model').Node} doc
 * @param {Set<string> | null} wanted ids to index; null indexes all
 */
function indexDoc(doc, wanted) {
  /** @type {Map<string, import('prosemirror-model').Node>} */
  const nodes = new Map();
  doc.descendants((node) => {
    const id = node.attrs?.id;
    if (typeof id === 'string' && (!wanted || wanted.has(id)) && !nodes.has(id)) nodes.set(id, node);
  });
  /** @type {Map<string, string>} */
  const hashes = new Map();
  return (/** @type {string} */ id) => {
    const node = nodes.get(id);
    if (!node) return null;
    let h = hashes.get(id);
    if (h === undefined) { h = nodeHash(node); hashes.set(id, h); }
    return h;
  };
}

/**
 * @param {(id: string) => string | null} hashOf
 * @param {unknown} r
 * @returns {DiscardReason | null}
 */
function judge(hashOf, r) {
  if (!wellFormed(r)) return 'malformed';
  const h = hashOf(r.nodeId);
  if (h === null) return 'missing';
  return h === r.hash ? null : 'changed';
}

/**
 * Admit one result against the current doc.
 * @param {import('prosemirror-model').Node} doc
 * @param {unknown} result
 * @returns {{admitted: true} | {admitted: false, reason: DiscardReason}}
 */
export function admitResult(doc, result) {
  if (!wellFormed(result)) return { admitted: false, reason: 'malformed' };
  const reason = judge(indexDoc(doc, new Set([result.nodeId])), result);
  return reason ? { admitted: false, reason } : { admitted: true };
}

/**
 * Filter results to fresh ones in input order. One doc walk; O(document nodes + results).
 * @template T
 * @param {import('prosemirror-model').Node} doc
 * @param {Iterable<T> | null | undefined} results
 * @returns {{fresh: T[], discarded: {nodeId: unknown, reason: DiscardReason}[],
 *   counts: Record<DiscardReason, number>}}
 */
export function filterFresh(doc, results) {
  const list = results ? Array.from(results) : [];
  /** @type {Set<string>} */
  const wanted = new Set();
  for (const r of list) if (wellFormed(r)) wanted.add(r.nodeId);
  const hashOf = indexDoc(doc, wanted);
  /** @type {T[]} */
  const fresh = [];
  /** @type {{nodeId: unknown, reason: DiscardReason}[]} */
  const discarded = [];
  const counts = { missing: 0, changed: 0, malformed: 0 };
  for (const r of list) {
    const reason = judge(hashOf, r);
    if (!reason) { fresh.push(r); continue; }
    counts[reason]++;
    const nodeId = r !== null && typeof r === 'object' ? /** @type {any} */ (r).nodeId : undefined;
    discarded.push({ nodeId, reason });
  }
  return { fresh, discarded, counts };
}

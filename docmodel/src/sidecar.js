// @ts-check
// NI-02: pure sidecar construction; NI-03 and ED-01 wire persistence/reattachment.
import { nodeHash } from './hash.js';

/**
 * @typedef {{id: string, path: number[], hash: string, type: string}} SidecarNode
 * @typedef {{version: number, nodes: SidecarNode[], genre?: null, links?: unknown[]}} Sidecar
 */

/** @param {import('prosemirror-model').Node} doc */
export function buildSidecar(doc) {
  /** @type {SidecarNode[]} */
  const nodes = [];
  /** @param {import('prosemirror-model').Node} node @param {number[]} path */
  const walk = (node, path) => {
    if (Object.hasOwn(node.attrs, 'id')) {
      if (node.attrs.id == null) throw new Error('sidecar: null id; run assignIds first');
      nodes.push({ id: node.attrs.id, path, hash: nodeHash(node), type: node.type.name });
    }
    node.forEach((child, offset, index) => walk(child, [...path, index]));
  };
  walk(doc, []);
  return { version: 1, nodes };
}

/** Validate the version-1 boundary and rebuild keys in their canonical order.
 * Reserved fields have no binding/link semantics until SL-01/SL-02.
 * @param {any} value
 * @returns {Sidecar}
 */
function canonicalSidecar(value) {
  const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  const nonempty = v => typeof v === 'string' && v.length > 0;
  if (!object(value)) throw new Error('sidecar: expected an object');
  if (value.version !== 1) throw new Error('sidecar: unsupported version (expected 1)');
  if (!Array.isArray(value.nodes)) throw new Error('sidecar: nodes must be an array');
  const ids = new Set();
  const nodes = value.nodes.map((entry, index) => {
    if (!object(entry) || !nonempty(entry.id) || !nonempty(entry.type) ||
        !Array.isArray(entry.path) || !entry.path.every(i => Number.isSafeInteger(i) && i >= 0) ||
        typeof entry.hash !== 'string' || !/^[0-9a-f]{64}$/.test(entry.hash)) {
      throw new Error(`sidecar: invalid node at index ${index}`);
    }
    if (ids.has(entry.id)) throw new Error(`sidecar: duplicate id at index ${index}`);
    ids.add(entry.id);
    return { id: entry.id, path: [...entry.path], hash: entry.hash, type: entry.type };
  });
  /** @type {Sidecar} */
  const result = { version: 1, nodes };
  if (Object.hasOwn(value, 'genre')) {
    if (value.genre !== null) throw new Error('sidecar: reserved genre must be null');
    result.genre = null;
  }
  if (Object.hasOwn(value, 'links')) {
    if (!Array.isArray(value.links)) throw new Error('sidecar: links must be an array');
    result.links = value.links;
  }
  return result;
}

/** @param {Sidecar} sidecar @returns {string} */
export function serializeSidecar(sidecar) {
  return JSON.stringify(canonicalSidecar(sidecar), null, 2) + '\n';
}

/** @param {string} text @returns {Sidecar} */
export function parseSidecar(text) {
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error('sidecar: malformed JSON');
  }
  return canonicalSidecar(value);
}

/** @param {string} docPath @returns {string} */
export function sidecarPath(docPath) {
  return `${docPath}.stw.json`;
}

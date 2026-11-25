// @ts-check
// NI-02: pure sidecar construction; NI-03 and ED-01 wire persistence/reattachment.
// SL-01: `genre` binds the document to one genre file content+version (its version key).
import { nodeHash } from './hash.js';

/**
 * @typedef {{id: string, path: number[], hash: string, type: string}} SidecarNode
 * @typedef {{node: string, from: number, to: number, sources: string[]}} SidecarLink
 * @typedef {{genre: string, genre_version: number, genre_hash: string}} GenreBinding
 * @typedef {{version: number, nodes: SidecarNode[], genre?: GenreBinding | null, links?: SidecarLink[]}} Sidecar
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

const BINDING_KEYS = ['genre', 'genre_version', 'genre_hash'];

/** Validate a genre binding and rebuild it in canonical key order; null stays null.
 * @param {any} value
 * @returns {GenreBinding | null}
 */
function canonicalBinding(value) {
  if (value === null) return null;
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('sidecar: genre must be null or an object');
  }
  for (const key of Object.keys(value)) {
    if (!BINDING_KEYS.includes(key)) throw new Error(`sidecar: genre has unknown key ${key}`);
  }
  if (typeof value.genre !== 'string' || value.genre.length === 0) {
    throw new Error('sidecar: genre.genre must be a non-empty string');
  }
  if (!Number.isSafeInteger(value.genre_version) || value.genre_version < 1) {
    throw new Error('sidecar: genre.genre_version must be an integer >= 1');
  }
  if (typeof value.genre_hash !== 'string' || !/^[0-9a-f]{64}$/.test(value.genre_hash)) {
    throw new Error('sidecar: genre.genre_hash must be 64 lowercase hex');
  }
  return { genre: value.genre, genre_version: value.genre_version, genre_hash: value.genre_hash };
}

const LINK_KEYS = ['node', 'from', 'to', 'sources'];

/** SL-02: one span-to-source link; from/to are character offsets in the node's text content.
 * Rebuilt in canonical key order with sources sorted.
 * @param {any} value @param {number} index @returns {SidecarLink}
 */
function canonicalLink(value, index) {
  const at = `sidecar: links[${index}]`;
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${at} must be an object`);
  for (const key of Object.keys(value)) {
    if (!LINK_KEYS.includes(key)) throw new Error(`${at} has unknown key ${key}`);
  }
  if (typeof value.node !== 'string' || value.node.length === 0) throw new Error(`${at}.node must be a non-empty string`);
  if (!Number.isSafeInteger(value.from) || value.from < 0) throw new Error(`${at}.from must be an integer >= 0`);
  if (!Number.isSafeInteger(value.to) || value.to <= value.from) throw new Error(`${at}.to must be an integer > from`);
  const sources = value.sources;
  if (!Array.isArray(sources) || sources.length === 0 ||
      !sources.every(s => typeof s === 'string' && s.length > 0) || new Set(sources).size !== sources.length) {
    throw new Error(`${at}.sources must be a non-empty array of unique non-empty strings`);
  }
  return { node: value.node, from: value.from, to: value.to, sources: [...sources].sort() };
}

/** Validate the version-1 boundary and rebuild keys in their canonical order.
 * `links` entries are SL-02 span-to-source links (see canonicalLink).
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
    result.genre = canonicalBinding(value.genre);
  }
  if (Object.hasOwn(value, 'links')) {
    if (!Array.isArray(value.links)) throw new Error('sidecar: links must be an array');
    result.links = value.links.map(canonicalLink);
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

/** New sidecar with `binding` validated in place of `genre` (null unbinds); input untouched.
 * Unwired by design: ED-01 (open/save) and BH-06 wire it.
 * @param {Sidecar} sidecar @param {GenreBinding | null} binding @returns {Sidecar}
 */
export function bindGenre(sidecar, binding) {
  return canonicalSidecar({ ...sidecar, genre: binding });
}

/** Compare a sidecar's binding with a genre version key {genre, genre_version, genre_hash}.
 * Unwired by design: ED-01 (open/save) and BH-06 wire it.
 * @param {Sidecar} sidecar @param {GenreBinding} versionKey
 * @returns {'unbound' | 'match' | 'stale' | 'other'}
 */
export function genreBindingStatus(sidecar, versionKey) {
  const bound = sidecar.genre;
  if (bound == null) return 'unbound';
  if (bound.genre !== versionKey.genre) return 'other';
  return bound.genre_version === versionKey.genre_version && bound.genre_hash === versionKey.genre_hash
    ? 'match' : 'stale';
}

// @ts-check
// DM-05 failure policy. Unwired by design: ED-01/ED-02 (editor open path) consume openMarkdown.
// Pure: never writes files and never returns rewritten Markdown (invariant I1).
import { parseMarkdown } from './parse.js';
import { serializeMarkdown } from './serialize.js';
import { UnsupportedNodeError } from './errors.js';

/**
 * @typedef {import('prosemirror-model').Node} PMNode
 * @typedef {{doc: PMNode|null, readOnly: boolean, warnings: string[]}} OpenResult
 */

/**
 * Open Markdown for editing. Read-only with a warning when the source has unsupported
 * constructs or does not reach a serialize fixed point.
 * @param {string} src
 * @param {{serialize?: (doc: PMNode) => string}} [opts] serialize: test seam only
 * @returns {OpenResult}
 */
export function openMarkdown(src, opts = {}) {
  if (typeof src !== 'string') throw new TypeError('openMarkdown: src must be a string');
  const serialize = opts.serialize ?? serializeMarkdown;
  let doc;
  try {
    doc = parseMarkdown(src);
  } catch (e) {
    if (e instanceof UnsupportedNodeError) {
      return { doc: null, readOnly: true, warnings: [`Opened read-only: ${e.message}`] };
    }
    throw e;
  }
  const reason = roundTripFailure(doc, serialize);
  if (reason) return { doc, readOnly: true, warnings: [`Opened read-only: does not round-trip (${reason})`] };
  return { doc, readOnly: false, warnings: [] };
}

/** @param {PMNode} doc @param {(d: PMNode) => string} serialize @returns {string|null} */
function roundTripFailure(doc, serialize) {
  try {
    const s1 = serialize(doc);
    const doc2 = parseMarkdown(s1);
    if (JSON.stringify(doc2.toJSON()) !== JSON.stringify(doc.toJSON())) return 'document changes after parse→serialize→parse';
    if (serialize(doc2) !== s1) return 'serialize is not a fixed point';
    return null;
  } catch (e) {
    return `re-parse failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

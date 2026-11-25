// @ts-check
import { Plugin } from 'prosemirror-state';
import { ulid } from './ids.js';

/**
 * Add attribute-only repairs to a transaction for this document. First occurrences keep
 * their ids. Does not mutate doc; positions stay valid because attributes do not change sizes.
 * O(document nodes) time and O(id-bearing nodes) memory, scoped to one document.
 * @param {import('prosemirror-model').Node} doc
 * @param {import('prosemirror-state').Transaction} tr transaction whose current doc is doc
 * @param {{ now?: () => number, rand?: (buf: Uint8Array) => Uint8Array | void }} [opts]
 * @returns {number} number of repaired nodes
 */
export function fixIds(doc, tr, opts = {}) {
  const seen = new Set();
  const now = opts.now ?? Date.now;
  let fixed = 0;
  doc.descendants((node, pos) => {
    if (!node.type.spec.attrs || !('id' in node.type.spec.attrs)) return;
    let id = node.attrs.id;
    if (id == null || seen.has(id)) {
      do id = ulid(now(), opts.rand); while (seen.has(id));
      tr.setNodeAttribute(pos, 'id', id);
      fixed++;
    }
    seen.add(id);
  });
  return fixed;
}

/**
 * NI-04 identity repairs join the triggering transaction's history event, so undo/redo
 * restore the same ids rather than generating replacements. fixIds is used here.
 * @param {{ now?: () => number, rand?: (buf: Uint8Array) => Uint8Array | void }} [opts]
 * @returns {Plugin}
 */
export function idPlugin(opts = {}) {
  return new Plugin({
    appendTransaction(_transactions, _oldState, newState) {
      const tr = newState.tr;
      return fixIds(newState.doc, tr, opts) ? tr : null;
    },
  });
}

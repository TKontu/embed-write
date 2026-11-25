// @ts-check
// HS-01: normalized text per node and its blake3 content hash.
//
// Normalization (stable contract; changing it invalidates every cache keyed by these hashes):
//   - text content of the node; marks (em/strong/link/code/...) and all attrs (ids, markers) ignored;
//   - hard_break counts as whitespace;
//   - each block boundary inside a container (paragraphs in a blockquote/list_item, list items,
//     table cells/rows) is separated by one space;
//   - atoms without text (image, html_block, front_matter, thematic_break) contribute nothing;
//   - every run of Unicode whitespace (\s, incl. NBSP and em space) collapses to one U+0020; trimmed.
//   - No Unicode NFC normalization (residual).
// Hash = blake3 over the UTF-8 bytes of the normalized text, 32 bytes, lowercase hex.
// Unwired by design: NI-02 (sidecar), HI-03 and PM-02 wire it.
import { blake3 } from '@noble/hashes/blake3';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';

/** @param {import('prosemirror-model').Node} node */
function collect(node, out) {
  if (node.isText) { out.push(node.text ?? ''); return; }
  if (node.type.name === 'hard_break') { out.push(' '); return; }
  node.forEach((child) => {
    if (child.isBlock) out.push(' ');
    collect(child, out);
  });
}

/** @param {import('prosemirror-model').Node} node @returns {string} */
export function normalizeText(node) {
  /** @type {string[]} */
  const out = [];
  collect(node, out);
  return out.join('').replace(/\s+/gu, ' ').trim();
}

/** @param {string} str @returns {string} 64-char lowercase hex blake3 digest */
export function hashText(str) {
  return bytesToHex(blake3(utf8ToBytes(str)));
}

/** @param {import('prosemirror-model').Node} node @returns {string} */
export function nodeHash(node) {
  return hashText(normalizeText(node));
}

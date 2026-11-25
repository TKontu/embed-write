// @ts-check
// HI-02: derived block layer over a ProseMirror doc. Pure; never writes into the doc.
import { sectionTree } from './sections.js';

/**
 * @typedef {'paragraph'|'list_item'|'table'|'figure'|'code'|'quote'|'heading'|'html'|
 *   'front_matter'|'footnote'|'thematic_break'} BlockKind
 * @typedef {{ kind: BlockKind, path: number[], text: string, section: number | null }} BlockEntry
 */

/** @type {Record<string, BlockKind>} */
const KIND = {
  paragraph: 'paragraph', heading: 'heading', blockquote: 'quote', list_item: 'list_item',
  code_block: 'code', thematic_break: 'thematic_break', html_block: 'html', table: 'table',
  front_matter: 'front_matter', footnote_definition: 'footnote',
};
const LISTS = new Set(['bullet_list', 'ordered_list']);

/** @param {import('prosemirror-model').Node} node */
const isFigure = (node) => node.childCount === 1 && node.firstChild?.type.name === 'image';

/**
 * Flat, document-ordered block entries. Lists are containers (their items are entries; nested
 * lists inside an item yield their own entries); quotes, tables, code and footnotes are one entry.
 * `section` is the top-level index of the innermost section's heading, or null for root.
 * @param {import('prosemirror-model').Node} doc
 * @returns {BlockEntry[]}
 */
export function blockLayer(doc) {
  /** @type {(number | null)[]} */
  const sectionOf = new Array(doc.childCount).fill(null);
  /** @param {import('./sections.js').Section} s */
  const assign = (s) => {
    const owner = s.heading ? s.heading.index : null;
    if (s.heading) sectionOf[s.heading.index] = owner;
    for (const i of s.blocks) sectionOf[i] = owner;
    s.children.forEach(assign);
  };
  assign(sectionTree(doc));

  /** @type {BlockEntry[]} */
  const out = [];
  /**
   * @param {import('prosemirror-model').Node} node
   * @param {number[]} path
   * @param {number | null} section
   */
  const visit = (node, path, section) => {
    const name = node.type.name;
    if (LISTS.has(name)) {
      node.forEach((item, _o, i) => visit(item, [...path, i], section));
      return;
    }
    const kind = name === 'paragraph' && isFigure(node) ? 'figure' : KIND[name];
    if (!kind) return;
    out.push({ kind, path, text: node.textContent, section });
    if (name === 'list_item') {
      node.forEach((child, _o, i) => {
        if (LISTS.has(child.type.name)) visit(child, [...path, i], section);
      });
    }
  };
  doc.forEach((node, _o, i) => visit(node, [i], sectionOf[i]));
  return out;
}

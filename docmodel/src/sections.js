// @ts-check
// HI-01: derived section tree from top-level headings. Pure; never writes into the doc.

/**
 * @typedef {{ level: number, heading: { text: string, index: number } | null,
 *   blocks: number[], children: Section[] }} Section
 */

/**
 * Build a nested section tree over a ProseMirror doc's top-level children.
 * Only top-level headings start sections; a heading nests under the nearest preceding
 * section of lower level (skipped levels tolerated). Indices are top-level child indices.
 * Single O(n) pass over top-level nodes.
 * @param {import('prosemirror-model').Node} doc
 * @returns {Section}
 */
export function sectionTree(doc) {
  /** @type {Section} */
  const root = { level: 0, heading: null, blocks: [], children: [] };
  /** @type {Section[]} */
  const stack = [root];
  doc.forEach((node, _offset, index) => {
    if (node.type.name === 'heading') {
      const level = Number(node.attrs.level);
      while (stack[stack.length - 1].level >= level) stack.pop();
      /** @type {Section} */
      const section = { level, heading: { text: node.textContent, index }, blocks: [], children: [] };
      stack[stack.length - 1].children.push(section);
      stack.push(section);
    } else {
      stack[stack.length - 1].blocks.push(index);
    }
  });
  return root;
}

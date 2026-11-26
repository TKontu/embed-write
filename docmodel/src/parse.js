// @ts-check
/**
 * DM-01 parse pipeline: Markdown text -> mdast (remark-parse + remark-gfm + remark-frontmatter)
 * -> ProseMirror doc under `schema`.
 */
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkFrontmatter from 'remark-frontmatter';
import { schema } from './schema.js';
import { UnsupportedNodeError } from './errors.js';

const processor = unified().use(remarkParse).use(remarkGfm).use(remarkFrontmatter, ['yaml', 'toml']);

/** @typedef {import('prosemirror-model').Node} PMNode */
/** @typedef {import('prosemirror-model').Mark} PMMark */
/** @typedef {{type: string, children?: any[], position?: any, [k: string]: any}} MdNode */

/**
 * Parse Markdown into a ProseMirror document.
 * @param {string} text
 * @returns {PMNode}
 */
export function parseMarkdown(text) {
  const tree = /** @type {MdNode} */ (processor.parse(text));
  /** @type {Map<string, MdNode>} */
  const defs = new Map();
  collectDefinitions(tree, defs);
  const ctx = { src: text, defs };
  return schema.node('doc', null, blockChildren(tree, ctx));
}

/** @param {MdNode} node @param {Map<string, MdNode>} defs */
function collectDefinitions(node, defs) {
  for (const child of node.children ?? []) {
    if (child.type === 'definition' && !defs.has(child.identifier)) defs.set(child.identifier, child);
    collectDefinitions(child, defs);
  }
}

/** @param {MdNode} node */
function startOffset(node) {
  return node.position?.start?.offset ?? 0;
}

/** @param {MdNode} node */
function unsupported(node) {
  return new UnsupportedNodeError(node.type, node.position?.start);
}

/** @param {MdNode} parent @param {any} ctx @returns {PMNode[]} */
function blockChildren(parent, ctx) {
  /** @type {PMNode[]} */
  const out = [];
  for (const child of parent.children ?? []) {
    if (child.type === 'definition') continue; // absorbed into link/image `ref` + href
    out.push(block(child, ctx));
  }
  return out;
}

/** @param {MdNode} node @param {any} ctx @returns {PMNode} */
function block(node, ctx) {
  const { src } = ctx;
  switch (node.type) {
    case 'paragraph':
      return schema.node('paragraph', null, inlineChildren(node, ctx, []));
    case 'heading':
      return schema.node('heading', {
        level: node.depth,
        setext: src[startOffset(node)] !== '#',
      }, inlineChildren(node, ctx, []));
    case 'blockquote':
      return schema.node('blockquote', null, blockChildren(node, ctx));
    case 'list': {
      const items = (node.children ?? []).map((/** @type {MdNode} */ item) => listItem(item, ctx));
      if (node.ordered) return schema.node('ordered_list', { start: node.start ?? 1 }, items);
      const marker = src[startOffset(node.children[0])];
      return schema.node('bullet_list', { marker }, items);
    }
    case 'code': {
      const m = /^ {0,3}(`{3,}|~{3,})/.exec(src.slice(startOffset(node)));
      return schema.node('code_block', {
        lang: node.lang ?? null,
        fence: m ? m[1] : '',
      }, node.value ? schema.text(node.value) : []);
    }
    case 'thematicBreak': {
      // FM-07: keep the source marker (---, ***, ___) so serialization reproduces the line.
      const m = /^ {0,3}([-*_])\1{2}/.exec(src.slice(startOffset(node)));
      return schema.node('thematic_break', m ? { marker: m[1].repeat(3) } : null);
    }
    case 'html':
      return schema.node('html_block', { value: node.value });
    case 'table': {
      const align = node.align ?? [];
      return schema.node('table', null, (node.children ?? []).map((/** @type {MdNode} */ row) => {
        if (row.type !== 'tableRow') throw unsupported(row);
        return schema.node('table_row', null, (row.children ?? []).map((/** @type {MdNode} */ cell, /** @type {number} */ i) => {
          if (cell.type !== 'tableCell') throw unsupported(cell);
          return schema.node('table_cell', { align: align[i] ?? null }, inlineChildren(cell, ctx, []));
        }));
      }));
    }
    case 'toml': // DM-03: recognised only to be rejected, never read as paragraph text
      throw new UnsupportedNodeError('toml (TOML front matter)', node.position?.start);
    case 'yaml':
      return schema.node('front_matter', { value: node.value });
    case 'footnoteDefinition':
      return schema.node('footnote_definition', { label: node.label ?? node.identifier }, blockChildren(node, ctx));
    default:
      throw unsupported(node);
  }
}

/** @param {MdNode} node @param {any} ctx */
function listItem(node, ctx) {
  if (node.type !== 'listItem') throw unsupported(node);
  return schema.node('list_item', { checked: node.checked ?? null }, blockChildren(node, ctx));
}

/** @param {MdNode} ref @param {any} ctx */
function resolveRef(ref, ctx) {
  const def = ctx.defs.get(ref.identifier);
  if (!def) throw new UnsupportedNodeError(`${ref.type} (undefined label "${ref.label}")`, ref.position?.start);
  return { href: def.url, title: def.title ?? null, ref: ref.label ?? ref.identifier };
}

/**
 * @param {MdNode} parent @param {any} ctx @param {readonly PMMark[]} marks
 * @returns {PMNode[]}
 */
function inlineChildren(parent, ctx, marks) {
  return (parent.children ?? []).flatMap((/** @type {MdNode} */ c) => inline(c, ctx, marks));
}

/** @param {readonly PMMark[]} marks @param {string} name @param {any} [attrs] */
function addMark(marks, name, attrs) {
  return schema.marks[name].create(attrs).addToSet(marks);
}

/**
 * @param {MdNode} node @param {any} ctx @param {readonly PMMark[]} marks
 * @returns {PMNode[]}
 */
function inline(node, ctx, marks) {
  const { src } = ctx;
  switch (node.type) {
    case 'text':
      return node.value ? [schema.text(node.value, marks)] : [];
    case 'emphasis':
      return inlineChildren(node, ctx, addMark(marks, 'em', { marker: src[startOffset(node)] }));
    case 'strong':
      return inlineChildren(node, ctx, addMark(marks, 'strong', { marker: src[startOffset(node)] }));
    case 'inlineCode':
      return node.value ? [schema.text(node.value, addMark(marks, 'code'))] : [];
    case 'break':
      return [schema.node('hard_break')];
    case 'link':
      return inlineChildren(node, ctx, addMark(marks, 'link', { href: node.url, title: node.title ?? null, ref: null }));
    case 'linkReference':
      return inlineChildren(node, ctx, addMark(marks, 'link', resolveRef(node, ctx)));
    case 'image':
      return [schema.node('image', { src: node.url, alt: node.alt ?? null, title: node.title ?? null, ref: null }, null, marks)];
    case 'imageReference': {
      const r = resolveRef(node, ctx);
      return [schema.node('image', { src: r.href, alt: node.alt ?? null, title: r.title, ref: r.ref }, null, marks)];
    }
    case 'footnoteReference': {
      const label = node.label ?? node.identifier;
      return [schema.text(label, addMark(marks, 'footnote_reference', { label }))];
    }
    default:
      throw unsupported(node);
  }
}

// @ts-check
// FM-05: paste into the rich editor. Production caller: createEditor (unwired in the app until AP-01).
// - text/html → ProseMirror DOMParser over docmodel's schema with the rules below: only
//   Markdown-representable structure survives; styles, classes and unknown tags are dropped and no
//   html_block is ever produced. Tables map to table/table_row/table_cell (GFM pipe table).
// - text/plain that looks like Markdown (LOOKS_MD) → docmodel parseMarkdown.
// - anything else (or Markdown that parseMarkdown rejects) → literal text, blank lines split paragraphs.
import { Plugin } from '@milkdown/prose/state';
import { DOMParser, Slice, Fragment } from '@milkdown/prose/model';
import { schema, parseMarkdown } from 'docmodel';

/** Block-level syntax at a line start, or unambiguous inline syntax. */
const LOOKS_MD = [
  /^#{1,6}[ \t]+\S/m, // ATX heading
  /^[ \t]{0,3}[-*+][ \t]+\S/m, // bullet item
  /^[ \t]{0,3}\d{1,9}[.)][ \t]+\S/m, // ordered item
  /^[ \t]{0,3}(```|~~~)/m, // code fence
  /^[ \t]{0,3}>[ \t]?\S/m, // blockquote
  /\*\*\S(?:[^*]*\S)?\*\*|__\S(?:[^_]*\S)?__/, // strong
  /(?:^|[\s(])\*\S(?:[^*\n]*\S)?\*(?=$|[\s).,;:!?])/m, // em with *
  /(?:^|[\s(])_\S(?:[^_\n]*\S)?_(?=$|[\s).,;:!?])/m, // em with _
  /\[[^\]\n]+\]\([^)\s]+(?:\s+"[^"]*")?\)/, // link
  /`[^`\n]+`/, // inline code
];
/** @param {string} text */
export const looksLikeMarkdown = (text) => LOOKS_MD.some((re) => re.test(text));

const heading = [1, 2, 3, 4, 5, 6].map((level) => ({ tag: `h${level}`, node: 'heading', attrs: { level } }));
const ignore = ['script', 'style', 'head', 'title', 'meta', 'link', 'template', 'noscript', 'iframe', 'object', 'svg', 'img']
  .map((tag) => ({ tag, ignore: true }));
/** @type {any[]} */
const rules = [
  ...ignore,
  ...heading,
  { tag: 'p', node: 'paragraph' },
  { tag: 'blockquote', node: 'blockquote' },
  { tag: 'ul', node: 'bullet_list' },
  { tag: 'ol', node: 'ordered_list', getAttrs: (/** @type {HTMLElement} */ d) => ({ start: Math.max(0, Number(d.getAttribute('start')) || 1) }) },
  { tag: 'li', node: 'list_item' },
  { tag: 'pre', node: 'code_block', preserveWhitespace: 'full' },
  { tag: 'hr', node: 'thematic_break' },
  { tag: 'table', node: 'table' },
  { tag: 'tr', node: 'table_row' },
  { tag: 'th', node: 'table_cell' },
  { tag: 'td', node: 'table_cell' },
  { tag: 'br', node: 'hard_break' },
  { tag: 'a[href]', mark: 'link', getAttrs: (/** @type {HTMLElement} */ d) => ({ href: d.getAttribute('href') }) },
  { tag: 'strong', mark: 'strong' },
  { tag: 'b', mark: 'strong' },
  { tag: 'em', mark: 'em' },
  { tag: 'i', mark: 'em' },
  { tag: 'code', mark: 'code' },
];
const htmlParser = new DOMParser(schema, rules);

/** @param {import('prosemirror-model').Fragment} content */
const openSlice = (content) => {
  const first = content.firstChild, last = content.lastChild;
  return new Slice(content, first?.type === schema.nodes.paragraph ? 1 : 0, last?.type === schema.nodes.paragraph ? 1 : 0);
};

/** @param {string} text */
function plainSlice(text) {
  const paras = text.replace(/\r\n?/g, '\n').split(/\n{2,}/).filter((p) => p.length);
  const nodes = paras.map((p) => {
    const parts = p.split('\n');
    /** @type {import('prosemirror-model').Node[]} */
    const inl = [];
    parts.forEach((s, i) => { if (i) inl.push(schema.nodes.hard_break.create()); if (s) inl.push(schema.text(s)); });
    return schema.nodes.paragraph.create(null, inl);
  });
  return openSlice(Fragment.from(nodes));
}

/**
 * @param {string} html
 * @param {Document} ownerDocument
 */
function htmlSlice(html, ownerDocument) {
  // Parse in an inert document: an element of the live document, even detached, still loads
  // resources and fires handlers such as <img onerror>.
  const inert = ownerDocument.implementation.createHTMLDocument('');
  inert.body.innerHTML = html;
  return openSlice(trimCode(htmlParser.parse(inert.body).content));
}

/**
 * <pre> text usually ends with the line's newline; Markdown fences carry it implicitly.
 * @param {import('prosemirror-model').Fragment} frag @returns {import('prosemirror-model').Fragment}
 */
function trimCode(frag) {
  /** @type {import('prosemirror-model').Node[]} */
  const out = [];
  frag.forEach((n) => {
    if (n.type === schema.nodes.code_block) {
      const t = n.textContent.replace(/\n$/, '');
      out.push(n.type.create(n.attrs, t ? schema.text(t) : null));
    } else out.push(n.isLeaf || n.isTextblock ? n : n.copy(trimCode(n.content)));
  });
  return Fragment.from(out);
}

/**
 * @param {{ isRich: () => boolean }} opts
 * @returns {Plugin}
 */
export function pastePlugin({ isRich }) {
  return new Plugin({
    props: {
      handlePaste(view, event) {
        if (!isRich()) return false;
        const data = event.clipboardData;
        if (!data) return false;
        const html = data.getData('text/html');
        const text = data.getData('text/plain');
        /** @type {Slice | null} */
        let slice = null;
        if (html && html.trim()) slice = htmlSlice(html, view.dom.ownerDocument);
        else if (text && looksLikeMarkdown(text)) {
          try { slice = openSlice(parseMarkdown(text).content); } catch { slice = null; }
        }
        if (!slice && text) slice = plainSlice(text);
        if (!slice || !slice.size) return false;
        event.preventDefault?.();
        view.dispatch(view.state.tr.replaceSelection(slice).scrollIntoView().setMeta('paste', true).setMeta('uiEvent', 'paste'));
        return true;
      },
    },
  });
}

// @ts-check
// ED-01: DOM rendering for docmodel's schema, which carries no toDOM (docmodel src is out of
// scope). Supplied to Milkdown as node/mark views; structure only, no CSS (non-goal).

/** @type {Record<string, (attrs: Record<string, any>) => { tag: string, attrs?: Record<string, string>, leaf?: boolean }>} */
const NODES = {
  paragraph: () => ({ tag: 'p' }),
  heading: (a) => ({ tag: `h${Math.min(Math.max(Number(a.level) || 1, 1), 6)}` }),
  blockquote: () => ({ tag: 'blockquote' }),
  bullet_list: () => ({ tag: 'ul' }),
  ordered_list: (a) => ({ tag: 'ol', attrs: a.start === 1 ? {} : { start: String(a.start) } }),
  list_item: (a) => ({ tag: 'li', attrs: a.checked == null ? {} : { 'data-checked': String(a.checked) } }),
  code_block: (a) => ({ tag: 'pre', attrs: a.lang ? { 'data-lang': String(a.lang) } : {} }),
  thematic_break: () => ({ tag: 'hr', leaf: true }),
  html_block: () => ({ tag: 'div', attrs: { 'data-type': 'html_block' }, leaf: true }),
  table: () => ({ tag: 'table' }),
  table_row: () => ({ tag: 'tr' }),
  table_cell: (a) => ({ tag: 'td', attrs: a.align ? { 'data-align': String(a.align) } : {} }),
  front_matter: () => ({ tag: 'div', attrs: { 'data-type': 'front_matter' }, leaf: true }),
  footnote_definition: (a) => ({ tag: 'div', attrs: { 'data-type': 'footnote_definition', 'data-label': String(a.label) } }),
  image: (a) => ({ tag: 'img', leaf: true, attrs: { src: String(a.src), ...(a.alt != null ? { alt: String(a.alt) } : {}) } }),
  hard_break: () => ({ tag: 'br', leaf: true }),
};

/** @type {Record<string, (attrs: Record<string, any>) => { tag: string, attrs?: Record<string, string> }>} */
const MARKS = {
  link: (a) => ({ tag: 'a', attrs: { href: String(a.href) } }),
  em: () => ({ tag: 'em' }),
  strong: () => ({ tag: 'strong' }),
  code: () => ({ tag: 'code' }),
  footnote_reference: (a) => ({ tag: 'sup', attrs: { 'data-label': String(a.label) } }),
};

/** @param {Document} doc @param {{ tag: string, attrs?: Record<string, string> }} d */
function el(doc, d) {
  const e = doc.createElement(d.tag);
  for (const [k, v] of Object.entries(d.attrs || {})) e.setAttribute(k, v);
  return e;
}

/**
 * Milkdown nodeViewCtx / markViewCtx entries for every rendered schema type.
 * @param {Document} doc
 */
export function views(doc) {
  const nodeViews = Object.entries(NODES).map(([name, f]) => [name, (/** @type {any} */ node) => {
    const d = f(node.attrs);
    const dom = el(doc, d);
    if (d.leaf) {
      if (node.attrs.value) dom.textContent = String(node.attrs.value);
      return { dom };
    }
    if (name === 'code_block') {
      const code = doc.createElement('code');
      dom.appendChild(code);
      return { dom, contentDOM: code };
    }
    return { dom, contentDOM: dom };
  }]);
  const markViews = Object.entries(MARKS).map(([name, f]) => [name, (/** @type {any} */ mark) => {
    const dom = el(doc, f(mark.attrs));
    return { dom, contentDOM: dom };
  }]);
  return { nodeViews, markViews, nodeNames: Object.keys(NODES), markNames: Object.keys(MARKS) };
}

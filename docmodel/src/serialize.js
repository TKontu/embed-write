// @ts-check
/**
 * DM-02 serializer: ProseMirror doc under `schema` -> Markdown, reproducing the source-convention
 * attrs DM-01 records (em/strong marker, heading setext, code fence, bullet marker, link/image ref).
 * Unwired by design: DM-03 (round-trip suite) and ED-01 consume serializeMarkdown.
 */

/** @typedef {import('prosemirror-model').Node} PMNode */
/** @typedef {import('prosemirror-model').Mark} PMMark */
/** @typedef {{ wrapWidth?: number }} SerializeOptions */

const BREAK = '\u0000'; // breakable space placeholder (from text content only)

/**
 * Serialize a ProseMirror doc back to Markdown.
 * @param {PMNode} doc
 * @param {SerializeOptions} [opts] wrapWidth: rewrap paragraphs at text spaces (default: no rewrap)
 * @returns {string}
 */
export function serializeMarkdown(doc, opts = {}) {
  /** @type {Map<string, {href: string, title: string|null}>} */
  const defs = new Map();
  const ctx = { opts, defs };
  const parts = children(doc, ctx);
  if (defs.size) {
    parts.push([...defs].map(([ref, d]) => `[${ref}]: ${destination(d.href)}${titlePart(d.title)}`).join('\n'));
  }
  return parts.length ? parts.join('\n\n') + '\n' : '';
}

/** @param {PMNode} node @param {any} ctx @returns {string[]} */
function children(node, ctx) {
  /** @type {string[]} */
  const out = [];
  node.forEach((child) => out.push(block(child, ctx)));
  return out;
}

/** List item blocks; a nested list directly follows its lead block (tight; spread is not recorded). */
/** @param {PMNode} item @param {any} ctx */
function itemBody(item, ctx) {
  const parts = children(item, ctx);
  let out = parts[0] ?? '';
  for (let i = 1; i < parts.length; i++) {
    const t = item.child(i).type.name;
    out += (t === 'bullet_list' || t === 'ordered_list' ? '\n' : '\n\n') + parts[i];
  }
  return out;
}

/** @param {string} text @param {string} first @param {string} rest */
function indent(text, first, rest) {
  return text.split('\n').map((l, i) => {
    const p = i === 0 ? first : rest;
    return l === '' ? p.trimEnd() : p + l;
  }).join('\n');
}

/** @param {PMNode} node @param {any} ctx @returns {string} */
function block(node, ctx) {
  switch (node.type.name) {
    case 'paragraph':
      return finishInline(inline(node, ctx, false), ctx.opts.wrapWidth);
    case 'heading': {
      const text = finishInline(inline(node, ctx, false));
      if (node.attrs.setext && node.attrs.level <= 2 && text) {
        const last = text.split('\n').pop() ?? '';
        return `${text}\n${(node.attrs.level === 1 ? '=' : '-').repeat(Math.max(3, last.length))}`;
      }
      return `${'#'.repeat(node.attrs.level)} ${text.replace(/#+$/, (m) => '\\' + m).replace(/\n/g, ' ')}`.trimEnd();
    }
    case 'blockquote':
      return indent(children(node, ctx).join('\n\n'), '> ', '> ');
    case 'bullet_list':
    case 'ordered_list': {
      const items = [];
      let n = node.attrs.start ?? 1;
      for (let i = 0; i < node.childCount; i++) {
        const item = node.child(i);
        const marker = node.type.name === 'bullet_list' ? node.attrs.marker : `${n++}.`;
        const box = item.attrs.checked === true ? '[x] ' : item.attrs.checked === false ? '[ ] ' : '';
        const body = itemBody(item, ctx);
        const pad = ' '.repeat(marker.length + 1);
        items.push(body ? indent(box + body, marker + ' ', pad) : marker + (box ? ' ' + box.trimEnd() : ''));
      }
      return items.join('\n');
    }
    case 'code_block': {
      const text = node.textContent;
      const { fence, lang } = node.attrs;
      if (fence === '' && !lang && text.trim() !== '') return indent(text, '    ', '    ');
      const ch = fence && fence[0] === '~' ? '~' : '`';
      let len = Math.max(3, fence ? fence.length : 3);
      for (const m of text.match(new RegExp(`^ {0,3}${ch === '`' ? '`' : '~'}{3,}`, 'gm')) ?? []) {
        len = Math.max(len, m.trim().length + 1);
      }
      const f = ch.repeat(len);
      return `${f}${lang ?? ''}\n${text ? text + '\n' : ''}${f}`;
    }
    case 'thematic_break':
      return '---';
    case 'html_block':
      return node.attrs.value;
    case 'front_matter':
      return `---\n${node.attrs.value}\n---`;
    case 'footnote_definition': {
      const body = children(node, ctx).join('\n\n');
      return indent(body, `[^${node.attrs.label}]: `, '    ').trimEnd();
    }
    case 'table': {
      const rows = [];
      node.forEach((row) => {
        const cells = [];
        row.forEach((cell) => cells.push(finishInline(inline(cell, ctx, true)).replace(/\n/g, ' ')));
        rows.push(`| ${cells.join(' | ')} |`);
      });
      const aligns = [];
      node.firstChild?.forEach((cell) => {
        aligns.push({ left: ':--', right: '--:', center: ':-:' }[cell.attrs.align] ?? '---');
      });
      rows.splice(1, 0, `| ${aligns.join(' | ')} |`);
      return rows.join('\n');
    }
    default:
      throw new Error(`serializeMarkdown: unknown block node ${node.type.name}`);
  }
}

/** Escape line-start constructs, then wrap (optional) and resolve break placeholders. */
/** @param {string} s @param {number} [width] */
function finishInline(s, width) {
  let lines = s.split('\n');
  if (width && width > 0) lines = lines.flatMap((l) => wrap(l, width));
  return lines.map((l) => escapeLineStart(l.split(BREAK).join(' '))).join('\n');
}

/** @param {string} line @param {number} width */
function wrap(line, width) {
  const words = line.split(BREAK);
  const out = [];
  let cur = '';
  for (const w of words) {
    if (cur && (cur + ' ' + w).length > width) { out.push(cur); cur = w; } else cur = cur ? cur + BREAK + w : w;
  }
  out.push(cur);
  return out;
}

/** @param {string} l */
function escapeLineStart(l) {
  return l
    .replace(/^(\s*)([#>+\-=])/, '$1\\$2')
    .replace(/^(\s*\d+)([.)])/, '$1\\$2');
}

/** @param {string} t @param {boolean} inTable */
function escapeText(t, inTable) {
  let s = t.replace(/[\\`*_[\]<~]/g, '\\$&').replace(/&(?=#?\w+;)/g, '\\&');
  if (inTable) s = s.replace(/\|/g, '\\|');
  return s;
}

/** @param {string} href */
function destination(href) {
  return /[\s<>]|^$/.test(href) || /[()]/.test(href) ? `<${href.replace(/[<>]/g, '\\$&')}>` : href;
}

/** @param {string|null} title */
function titlePart(title) {
  return title == null ? '' : ` "${title.replace(/["\\]/g, '\\$&')}"`;
}

/** @param {string} t */
function codeSpan(t) {
  const runs = t.match(/`+/g) ?? [];
  let n = 1;
  while (runs.some((r) => r.length === n)) n++;
  const tick = '`'.repeat(n);
  const pad = /^`|`$/.test(t) || (/^ .* $/.test(t) && t.trim() !== '') ? ' ' : '';
  return tick + pad + t + pad + tick;
}

const ORDER = ['link', 'em', 'strong'];

/** @param {PMMark} m @param {any} ctx */
function open(m) {
  if (m.type.name === 'link') return '[';
  const c = m.attrs.marker === '_' ? '_' : '*';
  return m.type.name === 'em' ? c : c + c;
}

/** @param {PMMark} m @param {any} ctx */
function close(m, ctx) {
  if (m.type.name !== 'link') return open(m);
  const { href, title, ref } = m.attrs;
  if (ref != null) {
    if (!ctx.defs.has(ref)) ctx.defs.set(ref, { href, title });
    return `][${ref}]`;
  }
  return `](${destination(href)}${titlePart(title)})`;
}

/**
 * Inline content with a mark stack; text spaces become BREAK placeholders.
 * @param {PMNode} parent @param {any} ctx @param {boolean} inTable
 */
function inline(parent, ctx, inTable) {
  /** @type {PMMark[]} */
  const stack = [];
  let out = '';
  /** @type {string|null} */
  let lastFootnote = null;
  const sync = (/** @type {readonly PMMark[]} */ marks) => {
    const keep = marks.filter((m) => ORDER.includes(m.type.name));
    let i = 0;
    while (i < stack.length && stack[i].isInSet(keep)) i++;
    while (stack.length > i) out += close(/** @type {PMMark} */ (stack.pop()), ctx);
    const add = keep.filter((m) => !m.isInSet(stack))
      .sort((a, b) => ORDER.indexOf(a.type.name) - ORDER.indexOf(b.type.name));
    for (const m of add) { out += open(m); stack.push(m); }
  };
  parent.forEach((node) => {
    sync(node.marks);
    const fn = node.marks.find((m) => m.type.name === 'footnote_reference');
    if (!fn) lastFootnote = null;
    if (fn) {
      if (lastFootnote !== fn.attrs.label) out += `[^${fn.attrs.label}]`;
      lastFootnote = fn.attrs.label;
    } else if (node.isText) {
      const t = node.text ?? '';
      if (node.marks.some((m) => m.type.name === 'code')) out += codeSpan(t);
      else out += escapeText(t, inTable).replace(/ /g, BREAK);
    } else if (node.type.name === 'hard_break') {
      out += '\\\n';
    } else if (node.type.name === 'image') {
      const { src, alt, title, ref } = node.attrs;
      const a = escapeText(alt ?? '', inTable);
      if (ref != null) {
        if (!ctx.defs.has(ref)) ctx.defs.set(ref, { href: src, title });
        out += `![${a}][${ref}]`;
      } else out += `![${a}](${destination(src)}${titlePart(title)})`;
    } else {
      throw new Error(`serializeMarkdown: unknown inline node ${node.type.name}`);
    }
  });
  sync([]);
  return out;
}

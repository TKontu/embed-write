// DM-04: seeded generators for the round-trip fuzz test (test-only, no dependencies).
import { schema } from '../src/index.js';

/** mulberry32 PRNG. @param {number} seed */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** @param {() => number} rnd */
export function makeRand(rnd) {
  const int = (n) => Math.floor(rnd() * n);
  const pick = (arr) => arr[int(arr.length)];
  const chance = (p) => rnd() < p;
  const range = (lo, hi) => lo + int(hi - lo + 1);
  return { int, pick, chance, range };
}

const WORDS = ['alpha', 'beta', 'gamma', 'delta', 'report', 'value', 'x', 'item', 'note', 'data', '42', 'é', 'naïve'];
// Markdown-special characters as standalone text tokens (escaped by the generator where needed).
const SPECIALS = ['\\*', '\\_', '\\`', '\\[', '\\]', '\\#', '\\<', '\\\\', '\\~', '1\\.', '\\+', '\\-', '\\>', '\\&amp;', '\\|', '(', ')', '!', '"', "'", ':', ';', ',', '.', '?', '%', '$', '@', '{', '}', '=', '^'];

/** Markdown text generator. @param {ReturnType<typeof makeRand>} r */
export function genMarkdown(r) {
  let fnCount = 0;
  const refs = new Map();
  const footnotes = [];

  const word = () => (r.chance(0.12) ? r.pick(SPECIALS) : r.pick(WORDS));
  const words = (lo, hi) => Array.from({ length: r.range(lo, hi) }, word).join(' ');

  /** @param {number} depth @param {boolean} inTable */
  const inlineSpan = (depth, inTable) => {
    const k = r.int(depth > 2 ? 2 : 11);
    switch (k) {
      case 0: case 1: return words(1, 3);
      case 2: { const m = r.pick(['*', '_']); return `${m}${words(1, 2)}${depth < 2 && r.chance(0.4) ? ' ' + strongSpan(depth + 1, inTable, true) : ''}${m}`; }
      case 3: return strongSpan(depth, inTable);
      case 4: return '`' + r.pick(['code', 'a*b', 'x_y', '[z]', '# h', 'a\\b', inTable ? 'p' : 'p|q', '<t>']) + '`';
      case 5: return `[${words(1, 2)}](${r.pick(['http://e.com/a', '/rel/path', 'b.md#s', '<a b>'])}${r.chance(0.3) ? ' "T"' : ''})`;
      case 6: {
        const label = r.pick(['r1', 'ref two', 'R3']);
        if (!refs.has(label.toLowerCase())) refs.set(label.toLowerCase(), `[${label}]: http://ref.example/${refs.size}${r.chance(0.3) ? ' "Ref"' : ''}`);
        return `[${words(1, 2)}][${label}]`;
      }
      case 7: return `![${r.chance(0.8) ? words(1, 2) : ''}](${r.pick(['img.png', '/a/b.jpg'])}${r.chance(0.3) ? ' "I"' : ''})`;
      case 8: {
        if (inTable) return words(1, 2);
        const label = `n${fnCount++}`;
        footnotes.push(`[^${label}]: ${words(2, 5)}`);
        return `${words(1, 2)}[^${label}]`;
      }
      case 9: if (r.chance(0.5)) { const label = r.pick(['r1', 'ref two', 'R3']); if (!refs.has(label.toLowerCase())) refs.set(label.toLowerCase(), `[${label}]: http://ref.example/i${refs.size}`); return `![${words(1, 1)}][${label}]`; } return words(1, 2);
      default: return words(1, 3);
    }
  };
  // Residual: em inside em (or strong inside strong) is not generated; the schema holds one mark per type.
  const strongSpan = (depth, inTable, inEm = false) => {
    const m = r.pick(['*', '_']);
    if (!inEm && depth < 2 && r.chance(0.4)) {
      const e = r.pick(['*', '_']);
      return `${m}${m}${words(1, 2)} ${e}${words(1, 2)}${e}${m}${m}`;
    }
    return `${m}${m}${words(1, 3)}${m}${m}`;
  };
  const inlineLine = (inTable = false) => Array.from({ length: r.range(1, 4) }, () => inlineSpan(0, inTable)).join(' ');
  const paragraph = () => {
    let s = inlineLine();
    if (r.chance(0.25)) s += r.pick(['\\\n', '  \n']) + inlineLine();
    return s;
  };

  const code = () => {
    const fence = r.pick(['```', '~~~', '````']);
    const lang = r.pick(['', 'js', 'python', 'md']);
    const body = Array.from({ length: r.range(0, 3) }, () => r.pick(['let x = 1;', '# not a heading', '* not a list', '| a | b |', '```', '  indented', '[x]: y', ''])).join('\n');
    const safeBody = fence === '```' ? body.replace(/^```/gm, '    ```') : body;
    return `${fence}${lang}\n${safeBody ? safeBody + '\n' : ''}${fence}`;
  };
  const table = () => {
    const cols = r.range(1, 4);
    const al = Array.from({ length: cols }, () => r.pick(['---', ':--', '--:', ':-:']));
    const row = () => `| ${Array.from({ length: cols }, () => inlineLine(true)).join(' | ')} |`;
    return [row(), `| ${al.join(' | ')} |`, ...Array.from({ length: r.range(0, 3) }, row)].join('\n');
  };
  const list = (depth) => {
    const ordered = r.chance(0.4);
    const marker = r.pick(['-', '*', '+']);
    const start = r.pick([1, 1, 3, 10]);
    const task = !ordered && r.chance(0.3);
    const items = [];
    for (let i = 0; i < r.range(1, 3); i++) {
      const m = ordered ? `${start + i}.` : marker;
      const pad = ' '.repeat(m.length + 1);
      const box = task ? r.pick(['[ ] ', '[x] ']) : '';
      let body = box + inlineLine();
      if (depth < 2 && r.chance(0.3)) body += '\n' + list(depth + 1);
      items.push(body.split('\n').map((l, j) => (j === 0 ? `${m} ${l}` : pad + l)).join('\n'));
    }
    return items.join('\n');
  };
  const heading = () => {
    const level = r.range(1, 6);
    if (level <= 2 && r.chance(0.4)) return `${inlineLine()}\n${(level === 1 ? '=' : '-').repeat(r.range(3, 8))}`;
    return `${'#'.repeat(level)} ${inlineLine()}`;
  };
  const blockquote = (depth) => {
    const inner = Array.from({ length: r.range(1, 2) }, () => (depth < 2 && r.chance(0.3) ? blockquote(depth + 1) : r.chance(0.3) ? list(1) : paragraph())).join('\n\n');
    return inner.split('\n').map((l) => (l ? '> ' + l : '>')).join('\n');
  };
  const blockGen = () => {
    switch (r.int(9)) {
      case 0: return heading();
      case 1: return list(0);
      case 2: return blockquote(0);
      case 3: return code();
      case 4: return table();
      case 5: return r.pick(['---', '***', '___', '- - -']);
      default: return paragraph();
    }
  };

  const blocks = [];
  if (r.chance(0.2)) blocks.push(`---\ntitle: ${r.pick(WORDS)}\ntags: [a, b]\n---`);
  const n = r.range(1, 6);
  for (let i = 0; i < n; i++) blocks.push(blockGen());
  for (const f of footnotes) blocks.push(f);
  for (const d of refs.values()) blocks.push(d);
  return blocks.join('\n\n') + '\n';
}

/** ProseMirror doc generator built from `schema`. @param {ReturnType<typeof makeRand>} r */
export function genDoc(r) {
  const s = schema;
  const m = s.marks;
  const txt = (marks = []) => s.text(Array.from({ length: r.range(1, 3) }, () => r.pick([...WORDS, '*', '_', '#', '[', ']', '`', '<', '\\', '|', '!', '&amp;', '1.', '-', '+', '>', '~'])).join(' '), marks);
  const inlines = (inTable = false) => {
    const out = [];
    for (let i = 0; i < r.range(1, 4); i++) {
      if (i > 0) out.push(s.text(' '));
      switch (r.int(8)) {
        case 0: out.push(txt([m.em.create({ marker: r.pick(['*', '_']) })])); break;
        case 1: out.push(txt([m.strong.create({ marker: r.pick(['*', '_']) })])); break;
        case 2: out.push(s.text(r.pick(['code', 'a`b', 'x|y', '* z']), [m.code.create()])); break;
        case 3: out.push(txt([m.link.create({ href: r.pick(['http://e.com', '/p q', 'a(b)']), title: r.pick([null, 'T', 'q"t']), ref: r.pick([null, null, 'rx']) })])); break;
        case 4: out.push(s.nodes.image.create({ src: r.pick(['i.png', 'a b.png']), alt: r.pick([null, 'alt', 'a*b']), title: r.pick([null, 'I']) })); break;
        case 5: if (!inTable) { out.push(txt()); out.push(s.nodes.hard_break.create()); } out.push(txt()); break;
        default: out.push(txt());
      }
    }
    return out;
  };
  const para = () => s.nodes.paragraph.create(null, inlines());
  const list = (depth) => {
    const ordered = r.chance(0.4);
    const task = !ordered && r.chance(0.3);
    const items = Array.from({ length: r.range(1, 3) }, () => {
      const kids = [para()];
      if (depth < 2 && r.chance(0.3)) kids.push(list(depth + 1));
      return s.nodes.list_item.create({ checked: task ? r.chance(0.5) : null }, kids);
    });
    return ordered ? s.nodes.ordered_list.create({ start: r.pick([1, 2, 7]) }, items) : s.nodes.bullet_list.create({ marker: r.pick(['-', '*', '+']) }, items);
  };
  const block = (depth) => {
    switch (r.int(8)) {
      case 0: { const level = r.range(1, 6); return s.nodes.heading.create({ level, setext: level <= 2 && r.chance(0.4) }, inlines()); }
      case 1: return list(0);
      case 2: return s.nodes.blockquote.create(null, [depth < 2 && r.chance(0.3) ? block(depth + 1) : para()]);
      case 3: { const t = r.pick(['x = 1', '```\ninner\n```', '~~~', '# h\n* l']); return s.nodes.code_block.create({ lang: r.pick([null, 'js']), fence: r.pick(['```', '~~~']) }, s.text(t)); }
      case 4: {
        const cols = r.range(1, 3);
        const aligns = Array.from({ length: cols }, () => r.pick([null, 'left', 'right', 'center']));
        const row = () => s.nodes.table_row.create(null, aligns.map((align) => s.nodes.table_cell.create({ align }, inlines(true))));
        return s.nodes.table.create(null, Array.from({ length: r.range(1, 3) }, row));
      }
      case 5: return s.nodes.thematic_break.create();
      default: return para();
    }
  };
  const blocks = [];
  if (r.chance(0.2)) blocks.push(s.nodes.front_matter.create({ value: 'title: t' }));
  for (let i = 0; i < r.range(1, 5); i++) blocks.push(block(0));
  return s.nodes.doc.create(null, blocks);
}

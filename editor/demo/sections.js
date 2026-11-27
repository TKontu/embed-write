// @ts-check
// CO-14 (D-015) demo half: inferred section boundaries from an intake sections.json shown as
// provisional markers (a widget badge "inferred · <method>") before the block they start. The
// document text is never rewritten: widgets are not part of the doc and do not serialize.
import { Decoration, DecorationSet } from '@milkdown/prose/view';
import { Plugin, PluginKey } from '@milkdown/prose/state';
import { parseMarkdown } from 'docmodel';

export const sectionMarkerKey = new PluginKey('demoSectionMarkers');

/**
 * Validate one document's inferred sections from sections.json ({start_line, level, method,
 * inferred: true, title_line}). Only inferred entries are kept.
 * @param {unknown} sections
 * @returns {Array<{ start_line: number, level: number, method: string }>}
 */
export function checkSections(sections) {
  if (!Array.isArray(sections)) throw new Error('sections must be a list');
  // A saved expert correction (inferred: false, method "expert") replaces the inferred set.
  return sections.filter((s) => s && (s.inferred === true || (s.inferred === false && s.method === 'expert'))).map((s) => {
    if (!Number.isInteger(s.start_line) || s.start_line < 0) throw new Error(`bad start_line: ${s.start_line}`);
    if (typeof s.method !== 'string' || !/^[a-z][a-z0-9_]*$/.test(s.method)) throw new Error(`bad method: ${s.method}`);
    return { start_line: s.start_line, level: Number.isInteger(s.level) ? s.level : 1, method: s.method };
  });
}

/** Python str.splitlines() boundaries: \r\n, \n, \r, \v, \f, \x1c-\x1e, \x85, U+2028, U+2029. */
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/g;

/**
 * Offsets where each line starts, numbering lines exactly as Python str.splitlines() (which
 * section_inference uses): no extra empty line after a final break.
 * @param {string} text @returns {number[]}
 */
export function lineStarts(text) {
  const starts = text.length ? [0] : [];
  for (const m of text.matchAll(LINE_BREAK)) {
    const next = m.index + m[0].length;
    if (next < text.length) starts.push(next);
  }
  return starts;
}

/** @param {string} text @returns {string[]} the lines of Python str.splitlines() */
export function splitLines(text) {
  const starts = lineStarts(text);
  return starts.map((start, i) => text.slice(start, i + 1 < starts.length ? starts[i + 1] : text.length)
    .replace(/(\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029])$/, ''));
}

/**
 * CO-14 (c): validate an expert section correction body {sections: [{start_line, level}]} for a
 * document of ``lineCount`` lines; returns the stored form (sorted, method "expert",
 * inferred false; line numbers and levels only, no text). Throws on any invalid entry.
 * @param {unknown} body @param {number} lineCount
 * @returns {Array<{ start_line: number, level: number, method: 'expert', inferred: false }>}
 */
export function checkSectionCorrection(body, lineCount) {
  const list = body && typeof body === 'object' ? /** @type {any} */ (body).sections : undefined;
  if (!Array.isArray(list)) throw new Error('body must be {sections: [...]}');
  const seen = new Set();
  const out = list.map((s) => {
    if (!s || typeof s !== 'object') throw new Error('each section must be an object');
    const extra = Object.keys(s).filter((k) => k !== 'start_line' && k !== 'level');
    if (extra.length) throw new Error(`unexpected field: ${extra[0]}`);
    if (!Number.isInteger(s.start_line) || s.start_line < 0 || s.start_line >= lineCount) {
      throw new Error(`bad start_line: ${s.start_line}`);
    }
    if (!Number.isInteger(s.level) || s.level < 1 || s.level > 6) throw new Error(`bad level: ${s.level}`);
    if (seen.has(s.start_line)) throw new Error(`duplicate start_line: ${s.start_line}`);
    seen.add(s.start_line);
    return { start_line: s.start_line, level: s.level, method: /** @type {'expert'} */ ('expert'), inferred: /** @type {false} */ (false) };
  });
  return out.sort((a, b) => a.start_line - b.start_line);
}

/**
 * Map each inferred section's 0-based source line to the top-level block it starts: the number of
 * top-level blocks in the source before that line. Lines past the end are dropped.
 * Residual: a line that does not start a block (e.g. a lazy continuation) marks the next block.
 * @param {string} markdown
 * @param {unknown} sections
 * @returns {Array<{ block: number, line: number, level: number, method: string }>}
 */
export function sectionMarkers(markdown, sections) {
  const starts = lineStarts(markdown);
  const total = parseMarkdown(markdown).childCount;
  const out = [];
  for (const s of checkSections(sections)) {
    if (s.start_line >= starts.length) continue;
    const prefix = markdown.slice(0, starts[s.start_line]);
    const block = s.start_line === 0 ? 0 : parseMarkdown(prefix).childCount;
    if (block < total) out.push({ block, line: s.start_line, level: s.level, method: s.method });
  }
  return out;
}

/** @param {Document} doc @param {{ line: number, method: string, level: number }} m */
function badge(doc, m) {
  const el = doc.createElement('div');
  el.className = 'provisional-section';
  el.setAttribute('contenteditable', 'false');
  el.dataset.method = m.method;
  el.dataset.line = String(m.line);
  el.dataset.level = String(m.level);
  const expert = m.method === 'expert';
  if (expert) el.classList.add('expert-section');
  el.title = expert ? 'Section boundary set by the expert (not in the text)'
    : 'Provisional section boundary (inferred, not in the text)';
  const label = doc.createElement('span');
  label.className = 'section-label';
  label.textContent = expert ? 'expert section' : `inferred · ${m.method}`;
  el.append(label);
  // CO-14 (c): the expert keeps (confirms) or removes each boundary; saved via the demo.
  for (const [action, text] of [['confirm', 'Keep'], ['remove', 'Remove']]) {
    const b = doc.createElement('button');
    b.type = 'button';
    b.className = `section-${action}`;
    b.dataset.action = action;
    b.textContent = text;
    el.append(b);
  }
  return el;
}

/**
 * @param {import('@milkdown/prose/model').Node} doc
 * @param {Array<{ block: number, line: number, level: number, method: string }>} markers
 */
export function sectionDecorations(doc, markers) {
  const starts = [];
  doc.forEach((_node, offset) => { starts.push(offset); });
  const decos = markers.filter((m) => m.block < starts.length).map((m) => Decoration.widget(
    starts[m.block], (view) => badge(view.dom.ownerDocument, m),
    { side: -1, ignoreSelection: true, key: `section-${m.line}-${m.method}`, marker: m }));
  return DecorationSet.create(doc, decos);
}

/** @param {Array<{ block: number, line: number, level: number, method: string }>} markers */
export function sectionMarkerPlugin(markers) {
  return new Plugin({
    key: sectionMarkerKey,
    state: {
      init: (_config, state) => sectionDecorations(state.doc, markers),
      apply: (tr, set) => set.map(tr.mapping, tr.doc),
    },
    props: { decorations: (state) => sectionMarkerKey.getState(state) },
  });
}

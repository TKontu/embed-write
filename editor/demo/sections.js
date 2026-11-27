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
  return sections.filter((s) => s && s.inferred === true).map((s) => {
    if (!Number.isInteger(s.start_line) || s.start_line < 0) throw new Error(`bad start_line: ${s.start_line}`);
    if (typeof s.method !== 'string' || !/^[a-z][a-z0-9_]*$/.test(s.method)) throw new Error(`bad method: ${s.method}`);
    return { start_line: s.start_line, level: Number.isInteger(s.level) ? s.level : 1, method: s.method };
  });
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
  const lines = markdown.split('\n');
  const total = parseMarkdown(markdown).childCount;
  const out = [];
  for (const s of checkSections(sections)) {
    if (s.start_line >= lines.length) continue;
    const prefix = lines.slice(0, s.start_line).join('\n');
    const block = s.start_line === 0 ? 0 : parseMarkdown(prefix + '\n').childCount;
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
  el.title = 'Provisional section boundary (inferred, not in the text)';
  el.textContent = `inferred · ${m.method}`;
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

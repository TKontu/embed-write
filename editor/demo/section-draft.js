// CO-14 (c, D-015): pure state of the demo's section-correction draft (no DOM). The expert keeps or
// removes each shown boundary and adds one at a 0-based source line (always level 1); the Save body
// is {sections: [{start_line, level}]}, which demo/server.js validates and stores as schema 1.

/**
 * @typedef {{ name: string, removed: Set<number>, added: Map<number, number>, markers: Array<{ line: number, level: number }> }} SectionDraft
 */

/** @param {string} name @param {Array<{ line: number, level: number }>} markers @returns {SectionDraft} */
export function createSectionDraft(name, markers) {
  return { name, removed: new Set(), added: new Map(), markers };
}

/** @param {SectionDraft} draft @param {number} line */
export function keepBoundary(draft, line) { draft.removed.delete(line); }

/** @param {SectionDraft} draft @param {number} line */
export function removeBoundary(draft, line) { draft.removed.add(line); }

/**
 * Add a level-1 boundary at ``line``; false (no change) unless it is a non-negative integer.
 * @param {SectionDraft} draft @param {number} line @returns {boolean}
 */
export function addBoundary(draft, line) {
  if (!Number.isInteger(line) || line < 0) return false;
  draft.added.set(line, 1);
  draft.removed.delete(line);
  return true;
}

/**
 * The Save body: kept shown boundaries plus added ones (an added line wins), sorted by line.
 * @param {SectionDraft} draft @returns {{ sections: Array<{ start_line: number, level: number }> }}
 */
export function sectionPayload(draft) {
  const keep = new Map(draft.markers.filter((m) => !draft.removed.has(m.line)).map((m) => [m.line, m.level]));
  for (const [l, level] of draft.added) keep.set(l, level);
  const sections = [...keep].map(([start_line, level]) => ({ start_line, level }))
    .sort((a, b) => a.start_line - b.start_line);
  return { sections };
}

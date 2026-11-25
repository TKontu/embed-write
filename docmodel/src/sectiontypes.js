// @ts-check
// HI-04: map top-level headings to genre section types. Pure; never writes into the doc.
// normalizeHeading is twinned by service/genre.py normalize_heading (fixture
// docmodel/test/fixtures/heading-normalize.json).
import { sectionTree } from './sections.js';

// Leading section number followed by whitespace: "3", "3.", "3.2", "3.2.", "IV.", "A.".
const SECTION_NUMBER = /^(?:\d+(?:\.\d+)*\.?|[IVXLCDM]+\.|[A-Z]\.)\s+/;

/**
 * Normalize a heading for exact alias matching: NFKC, trim, strip a leading section
 * number, strip trailing ':' / '.', collapse whitespace, lowercase.
 * @param {string} text
 * @returns {string}
 */
export function normalizeHeading(text) {
  let s = String(text).normalize('NFKC').trim();
  s = s.replace(SECTION_NUMBER, '');
  s = s.replace(/[:.]+$/, '');
  return s.replace(/\s+/g, ' ').trim().toLowerCase();
}

/**
 * @typedef {{ id: string, name: string, headings: string[] }} SectionType
 * @typedef {{ heading: string, index: number, level: number, sectionType: string }} MappedHeading
 * @typedef {{ heading: string, index: number, level: number }} UnmappedHeading
 */

/**
 * Map every top-level heading to a section type id by exact normalized alias match,
 * or report it as unmapped. Document order. No fuzzy matching.
 * @param {import('prosemirror-model').Node} doc
 * @param {SectionType[] | undefined} sectionTypes genre file `section_types` (validated by service/genre.py)
 * @returns {{ mapped: MappedHeading[], unmapped: UnmappedHeading[] }}
 */
export function mapSectionTypes(doc, sectionTypes) {
  /** @type {Map<string, string>} */
  const alias = new Map();
  for (const t of sectionTypes ?? []) {
    for (const h of t.headings) alias.set(normalizeHeading(h), t.id);
  }
  /** @type {MappedHeading[]} */
  const mapped = [];
  /** @type {UnmappedHeading[]} */
  const unmapped = [];
  /** @param {import('./sections.js').Section} s */
  const walk = (s) => {
    if (s.heading) {
      const entry = { heading: s.heading.text, index: s.heading.index, level: s.level };
      const id = alias.get(normalizeHeading(s.heading.text));
      if (id !== undefined) mapped.push({ ...entry, sectionType: id });
      else unmapped.push(entry);
    }
    s.children.forEach(walk);
  };
  walk(sectionTree(doc));
  return { mapped, unmapped };
}

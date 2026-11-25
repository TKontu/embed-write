// @ts-check
// HI-03: sentence layer. Lazy, cached by block content hash (HS-01 nodeHash), never stored in the
// ProseMirror doc or node attrs. Keys follow service/sentence_keys.py (NI-05): `<blockId>:<hash>`,
// the n-th repeat of a hash within the block gets `#n` (n >= 1); key is null without a blockId.
// Unwired by design; NI-05/ED-01 wire it.
// Residuals: the default splitter is a small rule set, not pysbd parity (no handling of ellipses,
// initials like "J. Smith", lowercase sentence starts, or abbreviations outside ABBREVIATIONS);
// cache memory is maxEntries * (one entry's sentence array: texts + 64-char hashes), unmeasured.
import { normalizeText, hashText } from './hash.js';

const ABBREVIATIONS = new Set([
  'e.g', 'i.e', 'etc', 'vs', 'cf', 'al', 'dr', 'mr', 'mrs', 'ms', 'prof', 'st', 'jr', 'sr',
  'fig', 'figs', 'no', 'nos', 'vol', 'p', 'pp', 'ch', 'sec', 'eq', 'approx', 'inc', 'ltd', 'co',
]);

// Terminal punctuation, optional closing quotes/brackets, whitespace, then a sentence start.
const BOUNDARY = /([.!?])["'”’)\]]*(\s+)(?=["'“‘(\[]?[\p{Lu}\p{N}])/gu;

/** Dependency-free rule splitter. @param {string} text @returns {string[]} */
export function defaultSegment(text) {
  const out = [];
  let start = 0;
  for (const m of text.matchAll(BOUNDARY)) {
    const end = /** @type {number} */ (m.index) + m[0].length - m[2].length;
    if (m[1] === '.') {
      const word = /(\S+)\.$/u.exec(text.slice(start, /** @type {number} */ (m.index) + 1));
      if (word && ABBREVIATIONS.has(word[1].toLowerCase().replace(/^[("'\[]+/u, ''))) continue;
    }
    out.push(text.slice(start, end));
    start = end + m[2].length;
  }
  if (start < text.length) out.push(text.slice(start));
  return out.map((s) => s.trim()).filter((s) => s.length > 0);
}

/**
 * @param {{maxEntries?: number, segment?: (text: string) => string[]}} [opts]
 */
export function createSentenceLayer(opts = {}) {
  const maxEntries = opts.maxEntries ?? 10000;
  const segment = opts.segment ?? defaultSegment;
  /** @type {Map<string, {index:number,text:string,start:number,end:number,hash:string}[]>} */
  const cache = new Map();

  /** @param {string} text */
  function compute(text) {
    const result = [];
    let cursor = 0;
    for (const raw of segment(text)) {
      const s = raw.trim();
      if (!s) continue;
      let start = text.indexOf(s, cursor);
      if (start < 0) start = cursor; // segmenter changed the text; offsets best-effort
      const end = start + s.length;
      cursor = end;
      result.push({ index: result.length, text: s, start, end, hash: hashText(s) });
    }
    return result;
  }

  return {
    /**
     * @param {import('prosemirror-model').Node} blockNode
     * @param {string} [blockId]
     */
    sentences(blockNode, blockId) {
      const text = normalizeText(blockNode);
      const h = hashText(text);
      let entry = cache.get(h);
      if (entry) {
        cache.delete(h);
        cache.set(h, entry);
      } else {
        entry = compute(text);
        cache.set(h, entry);
        while (cache.size > maxEntries) cache.delete(/** @type {string} */ (cache.keys().next().value));
      }
      /** @type {Map<string, number>} */
      const seen = new Map();
      return entry.map((s) => {
        const n = seen.get(s.hash) ?? 0;
        seen.set(s.hash, n + 1);
        const key = blockId ? `${blockId}:${s.hash}${n === 0 ? '' : `#${n}`}` : null;
        return { ...s, key };
      });
    },
    get size() { return cache.size; },
  };
}

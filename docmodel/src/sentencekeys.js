// @ts-check
// NI-05: document-level sentence addresses. A key is `<blockId>:<hash>[#n]` as produced by
// createSentenceLayer (HI-03) and service/sentence_keys.py; the owning node is the id-bearing node
// that directly holds inline content (textblocks). Nodes with a null id are skipped.
// Unwired by design; ED-01 / edit log wire it.
// Residual: sentenceIndex is O(document text) per call; resolveSentenceKey walks the doc to find
// the block (O(nodes)) — no position index is kept.
import { createSentenceLayer } from './sentences.js';

const KEY = /^([^:#]+):([^:#]+)(?:#([1-9]\d*))?$/u;

/** @param {unknown} key @returns {{blockId:string,hash:string,repeat:number}|null} */
export function parseSentenceKey(key) {
  if (typeof key !== 'string') return null;
  const m = KEY.exec(key);
  if (!m) return null;
  return { blockId: m[1], hash: m[2], repeat: m[3] ? Number(m[3]) : 0 };
}

/** @param {import('prosemirror-model').Node} doc @param {(node: any, pos: number) => boolean|void} fn */
function eachTextblock(doc, fn) {
  let stop = false;
  doc.descendants((node, pos) => {
    if (stop) return false;
    if (node.isTextblock) {
      const id = node.attrs.id;
      if (typeof id === 'string' && id && fn(node, pos)) stop = true;
      return false;
    }
    return true;
  });
}

/**
 * @param {import('prosemirror-model').Node} doc
 * @param {ReturnType<typeof createSentenceLayer>} [layer]
 */
export function sentenceIndex(doc, layer = createSentenceLayer()) {
  /** @type {{key:string,blockId:string,index:number,start:number,end:number,text:string,hash:string}[]} */
  const out = [];
  eachTextblock(doc, (node) => {
    const blockId = node.attrs.id;
    for (const s of layer.sentences(node, blockId)) {
      out.push({ key: /** @type {string} */ (s.key), blockId, index: s.index, start: s.start, end: s.end, text: s.text, hash: s.hash });
    }
  });
  return out;
}

/**
 * @param {import('prosemirror-model').Node} doc
 * @param {string} key
 * @param {ReturnType<typeof createSentenceLayer>} [layer]
 */
export function resolveSentenceKey(doc, key, layer = createSentenceLayer()) {
  const parsed = parseSentenceKey(key);
  if (!parsed) return null;
  /** @type {{blockId:string,pos:number,index:number,start:number,end:number,text:string}|null} */
  let found = null;
  eachTextblock(doc, (node, pos) => {
    if (node.attrs.id !== parsed.blockId) return false;
    const s = layer.sentences(node, parsed.blockId).find((x) => x.key === key);
    if (s) found = { blockId: parsed.blockId, pos, index: s.index, start: s.start, end: s.end, text: s.text };
    return true;
  });
  return found;
}

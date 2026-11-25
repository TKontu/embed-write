// @ts-check
/**
 * NI-01: ULID block node ids. Unwired by design; NI-02 (sidecar) and ED-01 wire them.
 * IDs live in node attrs only and never reach serialized Markdown (I1).
 */
import { Fragment } from 'prosemirror-model';

const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
const TIME_LEN = 10;
const RAND_LEN = 16;

/** @param {Uint8Array} buf */
const cryptoRandom = (buf) => globalThis.crypto.getRandomValues(buf);

let lastTime = -1;
/** @type {number[]} */
let lastRand = [];

/**
 * 26-char Crockford base32 ULID. Within the same millisecond, ids increase monotonically
 * (random part incremented by one). Clock and random source are injectable for tests.
 * @param {number} [now] milliseconds since epoch
 * @param {(buf: Uint8Array) => Uint8Array | void} [rand] fills buf with random bytes
 * @returns {string}
 */
export function ulid(now = Date.now(), rand = cryptoRandom) {
  if (!Number.isInteger(now) || now < 0 || now > 2 ** 48 - 1) throw new RangeError('ulid: bad time');
  let digits;
  if (now === lastTime) {
    digits = lastRand.slice();
    let i = RAND_LEN - 1;
    while (i >= 0 && digits[i] === 31) digits[i--] = 0;
    if (i < 0) throw new RangeError('ulid: random component overflow within one millisecond');
    digits[i] += 1;
  } else {
    const buf = new Uint8Array(RAND_LEN);
    rand(buf);
    digits = Array.from(buf, (b) => b & 31);
  }
  lastTime = now;
  lastRand = digits;
  let t = now;
  let time = '';
  for (let i = 0; i < TIME_LEN; i++) {
    time = ALPHABET[t % 32] + time;
    t = Math.floor(t / 32);
  }
  return time + digits.map((d) => ALPHABET[d]).join('');
}

/**
 * Return a NEW doc where every node whose type declares an `id` attr has a unique id. Existing
 * ids are kept; a duplicate keeps its first (document-order) occurrence and later ones are
 * reassigned. The input is not mutated. One O(n) traversal.
 * @param {import('prosemirror-model').Node} doc
 * @param {{ now?: () => number, rand?: (buf: Uint8Array) => Uint8Array | void }} [opts]
 * @returns {import('prosemirror-model').Node}
 */
export function assignIds(doc, opts = {}) {
  const now = opts.now ?? Date.now;
  const rand = opts.rand;
  /** @type {Set<string>} */
  const seen = new Set();
  const fresh = () => {
    let id;
    do id = ulid(now(), rand); while (seen.has(id));
    return id;
  };
  /** @param {import('prosemirror-model').Node} node @returns {import('prosemirror-model').Node} */
  const walk = (node) => {
    const hasId = !!node.type.spec.attrs && 'id' in node.type.spec.attrs;
    if (node.isText || (node.isLeaf && !hasId)) return node;
    /** @type {import('prosemirror-model').Node[]} */
    const kids = [];
    let attrs = node.attrs;
    if (hasId) {
      let id = node.attrs.id;
      if (id == null || seen.has(id)) id = fresh();
      seen.add(id);
      if (id !== node.attrs.id) attrs = { ...node.attrs, id };
    }
    node.forEach((child) => kids.push(walk(child)));
    return node.type.create(attrs, Fragment.fromArray(kids), node.marks);
  };
  return walk(doc);
}

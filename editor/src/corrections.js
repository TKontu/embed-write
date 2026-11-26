// @ts-check
// IN-05 (D-009 thin-demo slice): expert label corrections from the inspector, move labels only.
// Mirrors analysis/label_precedence.py (DS-02): expert > slow_layer (> fast, the sidecar here);
// within a source the latest timestamp wins, a missing timestamp sorts earliest, ties go to the
// later position. Production caller: editor/demo/app.js. The future DS-01/PT-01 consumer and the
// app-shell wiring (AP-01) are owed. The demo store is a JSON file, not the SQLite edit log.

/** Ranked highest first. */
export const SOURCES = Object.freeze(['expert', 'slow_layer', 'fast']);
const RANK = new Map(SOURCES.map((s, i) => [s, SOURCES.length - i]));
export const EXPERT_LAYER = 'expert correction';
const PROVISIONAL_LAYER = 'provisional';

/**
 * @typedef {{ block: number, label: string, source: 'fast' | 'slow_layer' | 'expert', timestamp?: number }} Candidate
 * @typedef {{ block: number, label: string, previous: string | null, source: 'expert', timestamp: number }} Correction
 */

/** @param {unknown} n */
const isBlock = (n) => Number.isInteger(n) && /** @type {number} */ (n) >= 0;

/** @param {any} c @param {number} i */
function timestampOf(c, i) {
  const ts = c.timestamp;
  if (ts === undefined || ts === null) return -Infinity;
  if (typeof ts !== 'number' || Number.isNaN(ts)) throw new TypeError(`candidate ${i}: timestamp must be a number`);
  return ts;
}

/**
 * Pure: the winning label candidate for one block, or null for no candidates. Throws on an unknown
 * source, a missing block/label, or candidates for different blocks. O(candidates).
 * @param {Iterable<Candidate>} candidates @returns {Candidate | null}
 */
export function resolveMoveLabel(candidates) {
  /** @type {Candidate | null} */
  let best = null;
  /** @type {[number, number, number] | null} */
  let bestKey = null;
  let i = 0;
  for (const c of candidates) {
    if (!c || typeof c !== 'object') throw new TypeError(`candidate ${i}: must be an object`);
    if (!isBlock(c.block)) throw new TypeError(`candidate ${i}: missing block`);
    if (typeof c.label !== 'string' || !c.label) throw new TypeError(`candidate ${i}: missing label`);
    const rank = RANK.get(/** @type {string} */ (c.source));
    if (rank === undefined) throw new TypeError(`candidate ${i}: unknown source ${c.source}`);
    if (best && best.block !== c.block) throw new TypeError(`candidate ${i}: block ${c.block} differs from ${best.block}`);
    /** @type {[number, number, number]} */
    const key = [rank, timestampOf(c, i), i];
    if (!bestKey || key[0] > bestKey[0] || (key[0] === bestKey[0]
      && (key[1] > bestKey[1] || (key[1] === bestKey[1] && key[2] > bestKey[2])))) {
      best = c;
      bestKey = key;
    }
    i += 1;
  }
  return best;
}

/**
 * Validate a correction-record list; `moveIds` (when given) are the genre's move ids.
 * Throws a TypeError naming the first bad record. @param {unknown} list @param {Set<string>} [moveIds]
 * @returns {Correction[]}
 */
export function checkCorrections(list, moveIds) {
  if (!Array.isArray(list)) throw new TypeError('corrections must be an array');
  list.forEach((c, i) => {
    if (!c || typeof c !== 'object' || Array.isArray(c)) throw new TypeError(`correction ${i}: must be an object`);
    if (!isBlock(c.block)) throw new TypeError(`correction ${i}: block must be an int >= 0`);
    if (typeof c.label !== 'string' || !c.label) throw new TypeError(`correction ${i}: label must be a move id`);
    if (moveIds && !moveIds.has(c.label)) throw new TypeError(`correction ${i}: ${c.label} is not a genre move`);
    if (c.previous !== null && typeof c.previous !== 'string') throw new TypeError(`correction ${i}: previous must be a string or null`);
    if (c.source !== 'expert') throw new TypeError(`correction ${i}: source must be "expert"`);
    if (typeof c.timestamp !== 'number' || !Number.isFinite(c.timestamp)) throw new TypeError(`correction ${i}: timestamp must be ms`);
  });
  return /** @type {Correction[]} */ (list);
}

/**
 * Pure: sidecar entries with each corrected move entry relabelled (`move`, `layer: "expert
 * correction"`, `previous`: the sidecar's label); every other entry is copied with
 * `layer: "provisional"`. Non-move overlays and corrections for blocks with no move entry are left
 * alone. Inputs are not mutated. O(entries + corrections).
 * @param {any[]} entries @param {Correction[]} corrections @returns {any[]}
 */
export function applyCorrections(entries, corrections) {
  if (!Array.isArray(entries)) throw new TypeError('sidecar entries must be an array');
  checkCorrections(corrections);
  /** @type {Map<number, Candidate[]>} */
  const byBlock = new Map();
  for (const c of corrections) {
    const list = byBlock.get(c.block) ?? [];
    list.push({ block: c.block, label: c.label, source: 'expert', timestamp: c.timestamp });
    byBlock.set(c.block, list);
  }
  return entries.map((e) => {
    const isMove = (e.overlay ?? 'moves') === 'moves';
    const expert = isMove ? byBlock.get(e.block) : undefined;
    if (!expert) return { ...e, layer: PROVISIONAL_LAYER };
    const win = resolveMoveLabel([{ block: e.block, label: e.move, source: 'fast' }, ...expert]);
    if (!win || win.source !== 'expert') return { ...e, layer: PROVISIONAL_LAYER };
    return { ...e, move: win.label, layer: EXPERT_LAYER, previous: e.move };
  });
}

/**
 * Pure: the correction list plus one expert record for `block` (previous = the sidecar's move
 * label for that block, else null). Inputs are not mutated. Production caller: editor/demo/app.js.
 * @param {Correction[]} corrections @param {any[]} sidecar @param {number} block @param {string} label
 * @param {number} [now] ms timestamp @returns {Correction[]}
 */
export function addCorrection(corrections, sidecar, block, label, now = Date.now()) {
  const entry = sidecar.find((e) => e && e.block === block && (e.overlay ?? 'moves') === 'moves');
  const record = { block, label, previous: entry ? entry.move : null, source: /** @type {'expert'} */ ('expert'), timestamp: now };
  return checkCorrections([...corrections, record]);
}

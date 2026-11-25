// @ts-check
import { dirtySet, dirtyRanges } from './dirty.js';

/**
 * HS-03. Unwired by design; ED-01 wires this, HS-04 tests undo/redo.
 * Add consecutive transforms from the same document stream. Retained state is
 * bounded by ids and merged ranges since the last flush, not transform history.
 * Deleted nodes' ids may remain pending: consumers must look them up in the
 * current document. dirtySet itself still indexes a whole document per add.
 * dispose() discards pending work and permanently disables the coalescer.
 *
 * @param {{delayMs: number, onFlush: (value: {ids: Set<string>, ranges: {from: number, to: number}[]}) => void,
 *   now?: () => number, setTimer?: (callback: () => void, delay: number) => any,
 *   clearTimer?: (timer: any) => void}} options
 */
export function createCoalescer({ delayMs, onFlush, now = Date.now,
  setTimer = (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimer = timer => globalThis.clearTimeout(timer) }) {
  let ids = new Set();
  let ranges = [];
  let timer = null;
  let deadline = 0;
  let disposed = false;

  function cancel() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }

  function flush() {
    cancel();
    if (disposed || (!ids.size && !ranges.length)) return;
    const value = { ids, ranges };
    ids = new Set();
    ranges = [];
    onFlush(value);
  }

  function expire() {
    timer = null;
    const remaining = deadline - now();
    if (remaining > 0) timer = setTimer(expire, remaining);
    else flush();
  }

  function add(tr) {
    if (disposed) return;
    const nextIds = dirtySet(tr);
    const nextRanges = dirtyRanges(tr);
    if (!nextIds.size && !nextRanges.length) return;
    for (const id of nextIds) ids.add(id);
    ranges = ranges.map(range => {
      const from = tr.mapping.map(range.from, -1);
      const to = tr.mapping.map(range.to, 1);
      return { from: Math.min(from, to), to: Math.max(from, to) };
    }).concat(nextRanges).sort((a, b) => a.from - b.from || a.to - b.to);
    const merged = [];
    for (const range of ranges) {
      const last = merged[merged.length - 1];
      if (last && range.from <= last.to) last.to = Math.max(last.to, range.to);
      else merged.push(range);
    }
    ranges = merged;
    cancel();
    deadline = now() + delayMs;
    timer = setTimer(expire, delayMs);
  }

  function dispose() {
    cancel();
    ids = new Set();
    ranges = [];
    disposed = true;
  }

  return { add, flush, pending: () => new Set(ids), dispose };
}

// IA-03: typing is never blocked by analysis. The analysis service is simulated as stopped
// (never-settling promise), slow, throwing and rejecting; per-dispatch latency is compared to the
// same editor without the plugin. LLM-built synthetic document only. jsdom/state.apply latency is a
// proxy; real-browser latency stays a residual (EP-01).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { analysisRequestPlugin } = await import('../src/analysis.js');
const { EditorState } = await import('@milkdown/prose/state');
const { parseMarkdown, assignIds } = await import('docmodel');

const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n'));
let firstPos = 0;
doc.descendants((n, pos) => { if (!firstPos && n.type.name === 'paragraph') firstPos = pos; });

function clock() {
  let t = 0; let seq = 0;
  /** @type {Map<number, {at: number, fn: () => void}>} */
  const timers = new Map();
  return {
    now: () => t,
    setTimer: (fn, ms) => { timers.set(++seq, { at: t + ms, fn }); return seq; },
    clearTimer: (id) => { timers.delete(id); },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        const due = [...timers].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); t = due[1].at; due[1].fn();
      }
      t = end;
    },
  };
}

const N = 300;
const DELAY = 10;
const tick = () => new Promise((r) => setImmediate(r));

/** Dispatch N single-character inserts; a request fires after every dispatch (outside timing). */
async function measure(onRequest, errors) {
  const c = clock();
  const plugins = onRequest ? [analysisRequestPlugin({ delayMs: DELAY, onRequest,
    onError: (e) => errors?.push(e), now: c.now, setTimer: c.setTimer, clearTimer: c.clearTimer })] : [];
  let state = EditorState.create({ doc, plugins });
  const pv = plugins[0]?.spec.view({ get state() { return state; } });
  const times = [];
  for (let i = 0; i < N; i++) {
    const t0 = performance.now();
    state = state.apply(state.tr.insertText('x', firstPos + 1 + i));
    times.push(performance.now() - t0);
    c.advance(DELAY);
    if (i % 50 === 0) await tick();
  }
  await tick();
  pv?.destroy();
  times.sort((a, b) => a - b);
  return times[Math.floor(N / 2)];
}

const modes = {
  stopped: () => new Promise(() => {}),
  slow: () => new Promise((r) => { setTimeout(r, 5000).unref(); }),
  throwing: () => { throw new Error('service down'); },
  rejecting: () => Promise.reject(new Error('service error')),
};

test('(a) a rejected onRequest promise reaches onError, never unhandledRejection', async () => {
  const unhandled = [];
  const listener = (e) => unhandled.push(e);
  process.on('unhandledRejection', listener);
  try {
    const errors = [];
    const c = clock();
    const plugin = analysisRequestPlugin({ delayMs: DELAY, onRequest: modes.rejecting,
      onError: (e) => errors.push(e), now: c.now, setTimer: c.setTimer, clearTimer: c.clearTimer });
    let state = EditorState.create({ doc, plugins: [plugin] });
    const pv = plugin.spec.view({ get state() { return state; } });
    state = state.apply(state.tr.insertText('x', firstPos + 1));
    c.advance(DELAY);
    await tick(); await tick();
    assert.equal(errors.length, 1);
    assert.equal(/** @type {Error} */ (errors[0]).message, 'service error');
    // without onError a rejection is still swallowed
    const p2 = analysisRequestPlugin({ delayMs: DELAY, onRequest: modes.rejecting,
      now: c.now, setTimer: c.setTimer, clearTimer: c.clearTimer });
    let s2 = EditorState.create({ doc, plugins: [p2] });
    const pv2 = p2.spec.view({ get state() { return s2; } });
    s2 = s2.apply(s2.tr.insertText('x', firstPos + 1));
    c.advance(DELAY);
    await tick(); await tick();
    pv.destroy(); pv2.destroy();
    assert.deepEqual(unhandled, []);
  } finally {
    process.off('unhandledRejection', listener);
  }
});

test('(b) median dispatch latency stays within 2x plain + 0.5 ms for every service mode', async () => {
  await measure(null); // warm-up
  const plain = await measure(null);
  const limit = 2 * plain + 0.5;
  const report = { plain };
  for (const [name, fn] of Object.entries(modes)) {
    const errors = [];
    report[name] = await measure(fn, errors);
    if (name === 'throwing' || name === 'rejecting') assert.equal(errors.length, N, name);
  }
  console.log(`# IA-03 median dispatch ms (N=${N}): ${JSON.stringify(report)} limit=${limit}`);
  for (const name of Object.keys(modes)) assert.ok(report[name] <= limit, `${name} ${report[name]} > ${limit}`);
});

test('(c) a never-settling request does not stop the next debounced request', async () => {
  const c = clock();
  let calls = 0;
  const plugin = analysisRequestPlugin({ delayMs: DELAY, onRequest: () => { calls++; return new Promise(() => {}); },
    now: c.now, setTimer: c.setTimer, clearTimer: c.clearTimer });
  let state = EditorState.create({ doc, plugins: [plugin] });
  const pv = plugin.spec.view({ get state() { return state; } });
  state = state.apply(state.tr.insertText('x', firstPos + 1));
  c.advance(DELAY);
  await tick();
  state = state.apply(state.tr.insertText('y', firstPos + 1));
  c.advance(DELAY);
  assert.equal(calls, 2);
  pv.destroy();
});

// FP-03: jsdom profile of the mounted editor on a deterministic, LLM-built synthetic document with
// the signal overlay on. Dev tool, unwired by design. Not a browser profile.
// Usage: node bench/fp03-profile.js [words] [reps]   (default 100000 words, 5 repetitions)
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { setupDom } from '../test/dom.js';

setupDom();
const { createEditor, signalDecorationsPlugin, updateSignalOverlay } = await import('../src/index.js');

const VOCAB = ('the of model text block signal draft section evidence claim method result corpus reader ' +
  'argument structure paragraph sentence review revision analysis measure overlay editor writing ' +
  'context support topic register move expert sample genre').split(' ');

/** Deterministic synthetic markdown of ~`words` words: a heading every 12 blocks, a code block every 40. */
export function syntheticMarkdown(words) {
  let seed = 191;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const blocks = [];
  let n = 0;
  let i = 0;
  while (n < words) {
    if (i % 40 === 39) { blocks.push('```js\nconst x = 1;\n```'); i += 1; continue; }
    if (i % 12 === 0) { blocks.push(`# Section ${i / 12 + 1}`); n += 2; i += 1; continue; }
    const len = Math.min(40 + Math.floor(rnd() * 80), words - n);
    const w = Array.from({ length: Math.max(len, 1) }, () => VOCAB[Math.floor(rnd() * VOCAB.length)]);
    w[0] = w[0][0].toUpperCase() + w[0].slice(1);
    blocks.push(w.join(' ') + '.');
    n += w.length;
    i += 1;
  }
  return { markdown: blocks.join('\n\n') + '\n', words: n };
}

const stats = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  const r = (v) => Math.round(v * 100) / 100;
  return { median_ms: r(s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2), max_ms: r(s[s.length - 1]), runs_ms: xs.map(r) };
};

/** Profile mount, overlay enable, one keystroke and one granularity change, each `reps` times. */
export async function profile({ words = 100000, reps = 5 } = {}) {
  const { markdown, words: wordCount } = syntheticMarkdown(words);
  let peak = process.memoryUsage().heapUsed;
  const sample = () => { peak = Math.max(peak, process.memoryUsage().heapUsed); };
  const t = { mount: [], overlay_on: [], keystroke: [], granularity: [] };
  let blockCount = 0;
  let signalled = 0;
  for (let r = 0; r < reps; r += 1) {
    const root = document.body.appendChild(document.createElement('div'));
    let t0 = performance.now();
    const editor = await createEditor({ root, markdown });
    const { view } = editor;
    view.dispatch(view.state.tr); // settle docmodel block ids, as in FP-02
    t.mount.push(performance.now() - t0);
    sample();
    try {
      // Signals on every third top-level block (moves overlay), alternating paragraph / sentence level.
      const ids = [];
      view.state.doc.forEach((node) => ids.push(node.attrs.id));
      blockCount = ids.length;
      const signals = ids.filter((_, i) => i % 3 === 0).map((id, k) => ({ node_id: id, kind: `m${k % 5}`,
        confidence: (k % 10) / 10, layer: k % 2 ? 'confirmed' : 'provisional', level: k % 2 ? 'sentence' : 'paragraph' }));
      signalled = signals.length;
      view.updateState(view.state.reconfigure({
        plugins: [...view.state.plugins, signalDecorationsPlugin(() => [], { initiallyOn: false })] }));

      t0 = performance.now();
      updateSignalOverlay({ on: true, signals })(view.state, view.dispatch);
      t.overlay_on.push(performance.now() - t0);
      sample();
      const shown = root.querySelectorAll('.signal').length;
      if (shown === 0) throw new Error('overlay shows no signals');

      // One keystroke inside a mid-document signalled paragraph.
      let mid = Math.floor(ids.length / 2);
      while (mid % 3 !== 0 || view.state.doc.child(mid).type.name !== 'paragraph') mid += 1;
      let pos = 0;
      for (let i = 0; i < mid; i += 1) pos += view.state.doc.child(i).nodeSize;
      t0 = performance.now();
      view.dispatch(view.state.tr.insertText('Z', pos + 3));
      t.keystroke.push(performance.now() - t0);
      sample();

      t0 = performance.now();
      updateSignalOverlay({ granularity: 'sentence' })(view.state, view.dispatch);
      t.granularity.push(performance.now() - t0);
      sample();
    } finally {
      await editor.destroy();
      root.remove();
    }
  }
  return {
    item: 'FP-03', environment: 'jsdom (not a browser)', node: process.version,
    document: 'LLM-built synthetic, generated deterministically in memory',
    words: wordCount, blocks: blockCount, signalled_blocks: signalled, repetitions: reps,
    mount: stats(t.mount), overlay_on: stats(t.overlay_on), keystroke: stats(t.keystroke),
    granularity_change: stats(t.granularity),
    peak_heap_used_mb: Math.round(peak / 1048576 * 10) / 10,
    keystroke_over_50ms: Math.max(...t.keystroke) > 50,
  };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const words = Number(process.argv[2] ?? 100000);
  const reps = Number(process.argv[3] ?? 5);
  const out = await profile({ words, reps });
  const json = JSON.stringify(out, null, 2) + '\n';
  process.stdout.write(json);
  if (words === 100000) {
    const file = resolve(dirname(fileURLToPath(import.meta.url)), '../../experiments/results/FP-03-jsdom.json');
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, json);
  }
}
